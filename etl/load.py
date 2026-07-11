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
    # page_size=1000: laps alone is ~25k rows/season; the default of 100
    # would mean hundreds of round trips through the pooler.
    execute_values(cur, sql, [[row[c] for c in cols] for row in rows], page_size=1000)
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


def _load_fact_bundle(conn, bundle: dict[str, list[dict]], fact_table: str) -> dict[str, int]:
    """Upsert one per-race fact bundle inside a single transaction.

    FK order: circuits -> drivers/constructors -> races -> fact rows. Fact
    rows arrive keyed by refs + (season, round) and upsert on
    (race_id, driver_id) after resolution.
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
        fact_rows = [
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
            for row in bundle[fact_table]
        ]
        counts[fact_table] = upsert(cur, fact_table, fact_rows, ["race_id", "driver_id"])
    return counts


def load_results_bundle(conn, bundle: dict[str, list[dict]]) -> dict[str, int]:
    return _load_fact_bundle(conn, bundle, "results")


def load_sprint_bundle(conn, bundle: dict[str, list[dict]]) -> dict[str, int]:
    return _load_fact_bundle(conn, bundle, "sprint_results")


def load_qualifying_bundle(conn, bundle: dict[str, list[dict]]) -> dict[str, int]:
    return _load_fact_bundle(conn, bundle, "qualifying_results")


def _load_bare_ref_bundle(
    conn, bundle: dict[str, list[dict]], fact_table: str, conflict_cols: list[str]
) -> dict[str, int]:
    """Loader for datasets whose items carry only a bare driverId (pitstops, laps).

    No driver/constructor rows come with these bundles, so driver refs must
    already exist (load results for the season first) — unknown refs fail
    loudly rather than silently dropping rows.
    """
    counts: dict[str, int] = {}
    with conn, conn.cursor() as cur:
        counts["circuits"] = upsert(cur, "circuits", bundle["circuits"], ["circuit_ref"])
        counts["races"] = upsert(
            cur, "races", _resolve_races(cur, bundle["races"]), ["season", "round"]
        )

        race_ids = _race_id_map(cur, {row["season"] for row in bundle["races"]})
        driver_ids = _ref_map(cur, "drivers", "driver_ref", "driver_id")
        missing = {row["driver_ref"] for row in bundle[fact_table]} - driver_ids.keys()
        if missing:
            raise ValueError(
                f"unknown driver refs {sorted(missing)} — load results for this season "
                f"before {fact_table} so the drivers table is populated"
            )
        fact_rows = [
            {
                "race_id": race_ids[(row["season"], row["round"])],
                "driver_id": driver_ids[row["driver_ref"]],
                **{k: v for k, v in row.items() if k not in ("season", "round", "driver_ref")},
            }
            for row in bundle[fact_table]
        ]
        counts[fact_table] = upsert(cur, fact_table, fact_rows, conflict_cols)
    return counts


def load_pitstops_bundle(conn, bundle: dict[str, list[dict]]) -> dict[str, int]:
    return _load_bare_ref_bundle(conn, bundle, "pitstops", ["race_id", "driver_id", "stop_number"])


def load_laps_bundle(conn, bundle: dict[str, list[dict]]) -> dict[str, int]:
    return _load_bare_ref_bundle(conn, bundle, "laps", ["race_id", "driver_id", "lap_number"])


def load_status_bundle(conn, bundle: dict[str, list[dict]]) -> dict[str, int]:
    """Upsert status lookup rows; Jolpica's statusId is the natural key."""
    with conn, conn.cursor() as cur:
        return {"status": upsert(cur, "status", bundle["status"], ["status_id"])}


def load_standings_bundle(conn, bundle: dict[str, list[dict]]) -> dict[str, int]:
    """Upsert a transform_standings() bundle: both standings tables at once.

    Standings key on (season, round, entity) directly — no race FK — so the
    only resolution needed is entity ref -> surrogate id.
    """
    counts: dict[str, int] = {}
    with conn, conn.cursor() as cur:
        counts["drivers"] = upsert(cur, "drivers", bundle["drivers"], ["driver_ref"])
        counts["constructors"] = upsert(
            cur, "constructors", bundle["constructors"], ["constructor_ref"]
        )

        driver_ids = _ref_map(cur, "drivers", "driver_ref", "driver_id")
        driver_rows = [
            {
                "driver_id": driver_ids[row["driver_ref"]],
                **{k: v for k, v in row.items() if k != "driver_ref"},
            }
            for row in bundle["driver_standings"]
        ]
        counts["driver_standings"] = upsert(
            cur, "driver_standings", driver_rows, ["season", "round", "driver_id"]
        )

        constructor_ids = _ref_map(cur, "constructors", "constructor_ref", "constructor_id")
        constructor_rows = [
            {
                "constructor_id": constructor_ids[row["constructor_ref"]],
                **{k: v for k, v in row.items() if k != "constructor_ref"},
            }
            for row in bundle["constructor_standings"]
        ]
        counts["constructor_standings"] = upsert(
            cur,
            "constructor_standings",
            constructor_rows,
            ["season", "round", "constructor_id"],
        )
    return counts
