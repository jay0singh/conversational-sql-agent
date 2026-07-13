"""LangGraph NL->SQL agent.

Current shape (step 4 of the build):

    intake -> schema_context -> generate_sql -> validate -> execute
                     ^                |              |
                     |   (errors, attempts left) <---+
                     +--- feedback loop; after MAX_ATTEMPTS -> graceful failure

Validation errors and execution errors both feed back to the LLM verbatim,
so it can correct itself; execution runs as the read-only role with its
8-second statement timeout. Result formatting and memory are next steps.

    python -m agent.graph "Who won the 2021 drivers' championship?"
"""

from __future__ import annotations

import os
import sys
from typing import TypedDict

import psycopg2
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langgraph.graph import END, START, StateGraph

from agent.schema import get_agent_connection, schema_description, schema_tables
from agent.validation import validate_sql

load_dotenv()

DEFAULT_MODEL = "llama-3.3-70b-versatile"
MAX_ATTEMPTS = 3  # initial generation + 2 corrections

SQL_SYSTEM_PROMPT = """You translate questions about Formula 1 into a single PostgreSQL SELECT query.

Database schema (the only tables and columns that exist):
{schema}

Rules:
- Output exactly one SELECT statement and nothing else — no explanations, no markdown fences.
- Use only tables and columns from the schema above. Join through the listed foreign keys.
- driver_standings/constructor_standings are cumulative snapshots after each round: \
for "championship at the end of season X", filter season = X and round = (max round \
for that season in the standings table).
- Match people, teams, and circuits by their name columns (family_name, given_name, \
name) with ILIKE for case-insensitivity — never guess *_ref values.
- Race position 1 means the winner; results.points are race points only (sprints are \
in sprint_results).
- Include a LIMIT unless the query is a single-row aggregate.
- Seasons are integers like 2021; 'current season' means the largest season in races.
- Duration/time-like columns (pitstops.duration, laps.time, qualifying q1/q2/q3) are \
text and may hold empty strings or 'M:SS.mmm' formats. Before numeric math, filter to \
plain numbers (col ~ '^[0-9.]+$') and cast via nullif(col, '')::numeric.
"""


class AgentState(TypedDict, total=False):
    question: str
    schema_text: str
    sql: str
    validation_errors: list[str]
    feedback: str  # error text fed back to the LLM on retry
    attempts: int
    columns: list[str]
    rows: list[list]
    error: str  # execution error of the last attempt
    failure: str  # set only when the agent gives up gracefully


def intake(state: AgentState) -> AgentState:
    question = (state.get("question") or "").strip()
    if not question:
        raise ValueError("Empty question.")
    return {"question": question}


def schema_context(state: AgentState) -> AgentState:
    return {"schema_text": schema_description()}


def _llm() -> ChatGroq:
    return ChatGroq(
        model=os.environ.get("GROQ_MODEL", DEFAULT_MODEL),
        temperature=0,
    )


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    return text.strip().rstrip(";").strip()


def generate_sql(state: AgentState) -> AgentState:
    messages = [
        ("system", SQL_SYSTEM_PROMPT.format(schema=state["schema_text"])),
        ("user", state["question"]),
    ]
    if state.get("feedback"):
        # Show the model its own failed attempt plus the real error message.
        messages.append(("assistant", state.get("sql", "")))
        messages.append(
            (
                "user",
                f"That query failed with:\n{state['feedback']}\n"
                "Return a corrected single SELECT statement and nothing else.",
            )
        )
    response = _llm().invoke(messages)
    return {
        "sql": _strip_fences(response.content),
        "attempts": state.get("attempts", 0) + 1,
        "feedback": None,
        "error": None,
    }


def validate(state: AgentState) -> AgentState:
    sql, errors = validate_sql(state["sql"], schema_tables())
    feedback = "; ".join(errors) if errors else None
    return {"sql": sql, "validation_errors": errors, "feedback": feedback}


def execute(state: AgentState) -> AgentState:
    conn = get_agent_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(state["sql"])
            columns = [d.name for d in cur.description]
            rows = [list(row) for row in cur.fetchall()]
        return {"columns": columns, "rows": rows, "error": None}
    except psycopg2.Error as exc:
        message = str(exc).strip()
        return {"error": message, "feedback": message}
    finally:
        conn.close()


def fail(state: AgentState) -> AgentState:
    last_error = state.get("feedback") or "unknown error"
    return {
        "failure": (
            f"I couldn't produce a working query after {state.get('attempts', 0)} "
            f"attempts. Last error: {last_error}"
        )
    }


def _route_after_validate(state: AgentState) -> str:
    if not state["validation_errors"]:
        return "execute"
    return "retry" if state.get("attempts", 0) < MAX_ATTEMPTS else "fail"


def _route_after_execute(state: AgentState) -> str:
    if not state.get("error"):
        return "done"
    return "retry" if state.get("attempts", 0) < MAX_ATTEMPTS else "fail"


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("intake", intake)
    graph.add_node("schema_context", schema_context)
    graph.add_node("generate_sql", generate_sql)
    graph.add_node("validate", validate)
    graph.add_node("execute", execute)
    graph.add_node("fail", fail)
    graph.add_edge(START, "intake")
    graph.add_edge("intake", "schema_context")
    graph.add_edge("schema_context", "generate_sql")
    graph.add_edge("generate_sql", "validate")
    graph.add_conditional_edges(
        "validate",
        _route_after_validate,
        {"execute": "execute", "retry": "generate_sql", "fail": "fail"},
    )
    graph.add_conditional_edges(
        "execute",
        _route_after_execute,
        {"done": END, "retry": "generate_sql", "fail": "fail"},
    )
    graph.add_edge("fail", END)
    return graph.compile()


def main() -> None:
    question = " ".join(sys.argv[1:]).strip()
    if not question:
        raise SystemExit('usage: python -m agent.graph "your question"')
    result = build_graph().invoke({"question": question})

    print(f"[attempts: {result.get('attempts', 0)}]")
    if result.get("failure"):
        print(result["failure"])
        raise SystemExit(1)
    print(f"SQL: {result['sql']}\n")
    columns, rows = result["columns"], result["rows"]
    print(" | ".join(columns))
    for row in rows[:10]:
        print(" | ".join(str(value) for value in row))
    if len(rows) > 10:
        print(f"... ({len(rows)} rows total)")
    elif not rows:
        print("(no rows)")


if __name__ == "__main__":
    main()
