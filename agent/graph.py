"""LangGraph NL->SQL agent.

Current shape (step 2 of the build): intake -> schema_context -> generate_sql,
which produces a candidate SELECT and stops — validation, execution, retries,
and formatting are the next steps.

    python -m agent.graph "Who won the 2021 drivers' championship?"
"""

from __future__ import annotations

import os
import sys
from typing import TypedDict

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langgraph.graph import END, START, StateGraph

from agent.schema import schema_description, schema_tables
from agent.validation import validate_sql

load_dotenv()

DEFAULT_MODEL = "llama-3.3-70b-versatile"

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
"""


class AgentState(TypedDict, total=False):
    question: str
    schema_text: str
    sql: str
    validation_errors: list[str]


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
    response = _llm().invoke(
        [
            ("system", SQL_SYSTEM_PROMPT.format(schema=state["schema_text"])),
            ("user", state["question"]),
        ]
    )
    return {"sql": _strip_fences(response.content)}


def validate(state: AgentState) -> AgentState:
    sql, errors = validate_sql(state["sql"], schema_tables())
    return {"sql": sql, "validation_errors": errors}


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("intake", intake)
    graph.add_node("schema_context", schema_context)
    graph.add_node("generate_sql", generate_sql)
    graph.add_node("validate", validate)
    graph.add_edge(START, "intake")
    graph.add_edge("intake", "schema_context")
    graph.add_edge("schema_context", "generate_sql")
    graph.add_edge("generate_sql", "validate")
    graph.add_edge("validate", END)
    return graph.compile()


def main() -> None:
    question = " ".join(sys.argv[1:]).strip()
    if not question:
        raise SystemExit('usage: python -m agent.graph "your question"')
    result = build_graph().invoke({"question": question})
    if result.get("validation_errors"):
        print("REJECTED:")
        for error in result["validation_errors"]:
            print(f"  - {error}")
        raise SystemExit(1)
    print(result["sql"])


if __name__ == "__main__":
    main()
