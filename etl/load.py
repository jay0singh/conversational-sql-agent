"""Idempotent upserts into Supabase Postgres, in FK-safe order.

Dimension rows are upserted on their unique Jolpica *_ref columns; fact rows
arrive from transform.py carrying refs, which are swapped for surrogate
integer keys here before insert. Every write targets ON CONFLICT ... DO
UPDATE, so re-running any load leaves the database in the same state.
"""

from __future__ import annotations

import os

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import execute_values

load_dotenv()


def get_connection():
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        raise SystemExit("SUPABASE_DB_URL is not set — copy .env.example to .env and fill it in.")
    return psycopg2.connect(url, connect_timeout=10)


def upsert(cur, table: str, rows: list[dict], conflict_cols: list[str]) -> int:
    """Batch-insert rows, updating non-key columns when the natural key exists."""
    if not rows:
        return 0
    cols = list(rows[0].keys())
    update_cols = [c for c in cols if c not in conflict_cols]
    assignments = ", ".join(f"{c} = excluded.{c}" for c in update_cols)
    sql = (
        f"insert into {table} ({', '.join(cols)}) values %s "
        f"on conflict ({', '.join(conflict_cols)}) do update set {assignments}"
    )
    execute_values(cur, sql, [[row[c] for c in cols] for row in rows])
    return len(rows)


def _ref_map(cur, table: str, ref_col: str, id_col: str) -> dict[str, int]:
    """Jolpica string ref -> surrogate integer key, for FK resolution."""
    cur.execute(f"select {ref_col}, {id_col} from {table}")
    return dict(cur.fetchall())


def _race_id_map(cur, seasons: set[int]) -> dict[tuple[int, int], int]:
    """(season, round) -> surrogate race_id, for attaching FKs to fact rows."""
    cur.execute(
        "select season, round, race_id from races where season = any(%s)",
        (sorted(seasons),),
    )
    return {(season, rnd): race_id for season, rnd, race_id in cur.fetchall()}


def _resolve_races(cur, race_rows: list[dict]) -> list[dict]:
    """Swap circuit_ref for circuit_id on race rows."""
    circuit_ids = _ref_map(cur, "circuits", "circuit_ref", "circuit_id")
    return [
        {**{k: v for k, v in row.items() if k != "circuit_ref"},
         "circuit_id": circuit_ids[row["circuit_ref"]]}
        for row in race_rows
    ]


def load_calendar_bundle(conn, bundle: dict[str, list[dict]]) -> dict[str, int]:
    """Upsert a transform_calendar() bundle: circuits, then races."""
    counts: dict[str, int] = {}
    with conn, conn.cursor() as cur:
        counts["circuits"] = upsert(cur, "circuits", bundle["circuits"], ["circuit_ref"])
        counts["races"] = upsert(cur, "races", _resolve_races(cur, bundle["races"]), ["season", "round"])
    return counts


def load_results_bundle(conn, bundle: dict[str, list[dict]]) -> dict[str, int]:
    """Upsert a transform_results() bundle inside one transaction.

    FK order: circuits -> drivers/constructors -> races -> results.
    """
    counts: dict[str, int] = {}
    with conn, conn.cursor() as cur:
        counts["circuits"] = upsert(cur, "circuits", bundle["circuits"], ["circuit_ref"])
        counts["drivers"] = upsert(cur, "drivers", bundle["drivers"], ["driver_ref"])
        counts["constructors"] = upsert(
            cur, "constructors", bundle["constructors"], ["constructor_ref"]
        )
        counts["races"] = upsert(
            cur, "races", _resolve_races(cur, bundle["races"]), ["season", "round"]
        )

        race_ids = _race_id_map(cur, {row["season"] for row in bundle["races"]})
        driver_ids = _ref_map(cur, "drivers", "driver_ref", "driver_id")
        constructor_ids = _ref_map(cur, "constructors", "constructor_ref", "constructor_id")
        result_rows = [
            {
                "race_id": race_ids[(row["season"], row["round"])],
                "driver_id": driver_ids[row["driver_ref"]],
                "constructor_id": constructor_ids[row["constructor_ref"]],
                **{
                    k: v
                    for k, v in row.items()
                    if k not in ("season", "round", "driver_ref", "constructor_ref")
                },
            }
            for row in bundle["results"]
        ]
        counts["results"] = upsert(cur, "results", result_rows, ["race_id", "driver_id"])
    return counts
