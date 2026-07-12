"""Schema introspection for the NL->SQL agent.

Runs under the read-only f1_agent_ro role, so the picture handed to the LLM
and the validator is — by construction — exactly the surface the agent is
allowed to query: the 12 granted F1 tables. etl_state isn't granted, doesn't
appear in information_schema under this role, and therefore can't leak into
prompts. Table comments planted by the migrations (coverage caveats like
"pitstops exist from 2011") ride along from the catalog.
"""

from __future__ import annotations

import os
from functools import lru_cache

import psycopg2
from dotenv import load_dotenv

load_dotenv()


def get_agent_connection():
    url = os.environ.get("AGENT_DB_URL")
    if not url:
        raise SystemExit("AGENT_DB_URL is not set — apply migration 003 and add it to .env.")
    return psycopg2.connect(url, connect_timeout=10)


@lru_cache(maxsize=1)
def _catalog() -> dict[str, dict]:
    """table -> {columns: [(name, type)...], fks: [...], comment: str|None}."""
    conn = get_agent_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                select c.table_name, c.column_name, c.data_type,
                       obj_description(pgc.oid) as table_comment
                from information_schema.columns c
                join pg_class pgc on pgc.relname = c.table_name
                    and pgc.relnamespace = 'public'::regnamespace
                where c.table_schema = 'public'
                order by c.table_name, c.ordinal_position
                """
            )
            columns = cur.fetchall()

            cur.execute(
                """
                select tc.table_name, kcu.column_name,
                       ccu.table_name, ccu.column_name
                from information_schema.table_constraints tc
                join information_schema.key_column_usage kcu
                    on kcu.constraint_name = tc.constraint_name
                join information_schema.constraint_column_usage ccu
                    on ccu.constraint_name = tc.constraint_name
                where tc.constraint_type = 'FOREIGN KEY'
                    and tc.table_schema = 'public'
                """
            )
            fks = cur.fetchall()
    finally:
        conn.close()

    tables: dict[str, dict] = {}
    for table, column, data_type, comment in columns:
        entry = tables.setdefault(table, {"columns": [], "fks": [], "comment": comment})
        entry["columns"].append((column, data_type))
    for table, column, ref_table, ref_column in fks:
        if table in tables:
            tables[table]["fks"].append(f"{column} -> {ref_table}.{ref_column}")
    return tables


def schema_description() -> str:
    """One compact, LLM-ready description of every visible table."""
    lines: list[str] = []
    for table, info in sorted(_catalog().items()):
        lines.append(f"Table {table}:")
        lines.append(
            "  columns: " + ", ".join(f"{name} {dtype}" for name, dtype in info["columns"])
        )
        if info["fks"]:
            lines.append(f"  foreign keys: {'; '.join(sorted(set(info['fks'])))}")
        if info["comment"]:
            lines.append(f"  note: {info['comment']}")
    return "\n".join(lines)


def schema_tables() -> dict[str, set[str]]:
    """table -> set of column names, for reference validation."""
    return {
        table: {name for name, _ in info["columns"]}
        for table, info in _catalog().items()
    }
