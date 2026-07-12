"""Static validation of LLM-generated SQL before it touches the database.

AST-based (sqlglot), not regex-based: the statement must parse as PostgreSQL,
be exactly one SELECT (set operations of SELECTs allowed), reference only
tables and columns that exist in the agent's visible schema, and carry a
LIMIT no greater than LIMIT_CAP (injected or clamped by rewriting the tree).

Column checking is deliberately loose — a column passes if it exists in *any*
visible table or is an alias/CTE defined inside the query — so computed
aliases don't false-reject. Truly wrong table.column pairings that slip
through are caught at execution, whose error feeds the retry loop.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

LIMIT_CAP = 500


def validate_sql(sql: str, tables: dict[str, set[str]]) -> tuple[str, list[str]]:
    """Return (possibly rewritten SQL, errors). Empty errors == safe to run."""
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except sqlglot.errors.ParseError as exc:
        return sql, [f"query does not parse as PostgreSQL: {exc}"]

    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        return sql, [f"exactly one statement is allowed, got {len(statements)}"]
    stmt = statements[0]

    if not isinstance(stmt, (exp.Select, exp.Union)):
        return sql, [
            f"only SELECT queries are allowed, got {type(stmt).__name__.upper()}"
        ]

    errors: list[str] = []

    cte_names = {cte.alias_or_name.lower() for cte in stmt.find_all(exp.CTE)}
    for table in stmt.find_all(exp.Table):
        name = table.name.lower()
        if name not in tables and name not in cte_names:
            errors.append(f"unknown table: {name}")

    known_columns: set[str] = set().union(*tables.values()) if tables else set()
    local_names = cte_names | {
        alias.alias.lower()
        for alias in stmt.find_all(exp.Alias)
        if isinstance(alias.alias, str) and alias.alias
    }
    for column in stmt.find_all(exp.Column):
        name = column.name.lower()
        if name and name not in known_columns and name not in local_names:
            errors.append(f"unknown column: {name}")

    if errors:
        return sql, sorted(set(errors))

    limit_expr = stmt.args.get("limit")
    requested = None
    if limit_expr is not None:
        literal = limit_expr.expression
        if isinstance(literal, exp.Literal) and literal.is_int:
            requested = int(literal.this)
    if requested is None or requested > LIMIT_CAP:
        stmt = stmt.limit(LIMIT_CAP)

    return stmt.sql(dialect="postgres"), []
