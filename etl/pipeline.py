"""Run ETL pipelines end to end.

    python -m etl.pipeline --season 2024                      # race results
    python -m etl.pipeline --season 2026 --dataset calendar   # full season schedule
    python -m etl.pipeline --season 2024 --dataset sprint     # sprint results (2021+)
    python -m etl.pipeline --season 2024 --dataset qualifying # qualifying with Q1/Q2/Q3

backfill.py and incremental.py (later features) call the same functions.
"""

from __future__ import annotations

import argparse

from etl.extract import JolpicaClient
from etl.load import (
    get_connection,
    load_calendar_bundle,
    load_qualifying_bundle,
    load_results_bundle,
    load_sprint_bundle,
)
from etl.transform import (
    transform_calendar,
    transform_qualifying_results,
    transform_results,
    transform_sprint_results,
)


def run_results(season: int, client: JolpicaClient | None = None) -> dict[str, int]:
    client = client or JolpicaClient()
    races = client.fetch_season_results(season)
    bundle = transform_results(races)
    conn = get_connection()
    try:
        return load_results_bundle(conn, bundle)
    finally:
        conn.close()


def run_calendar(season: int, client: JolpicaClient | None = None) -> dict[str, int]:
    client = client or JolpicaClient()
    races = client.fetch_season_calendar(season)
    bundle = transform_calendar(races)
    conn = get_connection()
    try:
        return load_calendar_bundle(conn, bundle)
    finally:
        conn.close()


def run_sprints(season: int, client: JolpicaClient | None = None) -> dict[str, int]:
    client = client or JolpicaClient()
    races = client.fetch_season_sprints(season)
    bundle = transform_sprint_results(races)
    conn = get_connection()
    try:
        return load_sprint_bundle(conn, bundle)
    finally:
        conn.close()


def run_qualifying(season: int, client: JolpicaClient | None = None) -> dict[str, int]:
    client = client or JolpicaClient()
    races = client.fetch_season_qualifying(season)
    bundle = transform_qualifying_results(races)
    conn = get_connection()
    try:
        return load_qualifying_bundle(conn, bundle)
    finally:
        conn.close()


RUNNERS = {
    "results": run_results,
    "calendar": run_calendar,
    "sprint": run_sprints,
    "qualifying": run_qualifying,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Load one season's data into Supabase.")
    parser.add_argument("--season", type=int, required=True, help="e.g. 2024")
    parser.add_argument(
        "--dataset", choices=RUNNERS, default="results", help="what to load (default: results)"
    )
    args = parser.parse_args()
    counts = RUNNERS[args.dataset](args.season)
    print(
        f"season {args.season} {args.dataset} upserted: "
        + ", ".join(f"{k}={v}" for k, v in counts.items())
    )


if __name__ == "__main__":
    main()
