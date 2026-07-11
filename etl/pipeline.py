"""Run ETL pipelines end to end.

    python -m etl.pipeline --season 2024                      # race results
    python -m etl.pipeline --season 2026 --dataset calendar   # full season schedule
    python -m etl.pipeline --season 2024 --dataset sprint     # sprint results (2021+)
    python -m etl.pipeline --season 2024 --dataset qualifying # qualifying with Q1/Q2/Q3
    python -m etl.pipeline --season 2024 --dataset pitstops   # pit stops (2011+, needs results first)
    python -m etl.pipeline --season 2024 --dataset laps       # lap times (~300 requests/season)
    python -m etl.pipeline --season 2024 --dataset standings  # driver + constructor standings per round
    python -m etl.pipeline --season 2024 --dataset status     # finishing-status lookup rows

backfill.py and incremental.py (later features) call the same functions.
"""

from __future__ import annotations

import argparse

from etl.extract import JolpicaClient
from etl.load import (
    get_connection,
    load_calendar_bundle,
    load_laps_bundle,
    load_pitstops_bundle,
    load_qualifying_bundle,
    load_results_bundle,
    load_sprint_bundle,
    load_standings_bundle,
    load_status_bundle,
)
from etl.transform import (
    transform_calendar,
    transform_laps,
    transform_pitstops,
    transform_qualifying_results,
    transform_results,
    transform_sprint_results,
    transform_standings,
    transform_status,
)

FIRST_PITSTOP_SEASON = 2011  # the API has no pit-stop data before this
FIRST_SPRINT_SEASON = 2021  # sprint format introduced in 2021


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
    if season < FIRST_SPRINT_SEASON:
        # Skip the API round trip; there is nothing to fetch.
        return {"circuits": 0, "drivers": 0, "constructors": 0, "races": 0, "sprint_results": 0}
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


def run_pitstops(season: int, client: JolpicaClient | None = None) -> dict[str, int]:
    if season < FIRST_PITSTOP_SEASON:
        # Skip without spending ~25 API requests to learn there's nothing there.
        return {"circuits": 0, "races": 0, "pitstops": 0}
    client = client or JolpicaClient()
    races = client.fetch_season_pitstops(season)
    bundle = transform_pitstops(races)
    conn = get_connection()
    try:
        return load_pitstops_bundle(conn, bundle)
    finally:
        conn.close()


def run_laps(season: int, client: JolpicaClient | None = None) -> dict[str, int]:
    client = client or JolpicaClient()
    races = client.fetch_season_laps(season)
    bundle = transform_laps(races)
    conn = get_connection()
    try:
        return load_laps_bundle(conn, bundle)
    finally:
        conn.close()


def run_standings(season: int, client: JolpicaClient | None = None) -> dict[str, int]:
    client = client or JolpicaClient()
    driver_lists, constructor_lists = client.fetch_season_standings(season)
    bundle = transform_standings(driver_lists, constructor_lists)
    conn = get_connection()
    try:
        return load_standings_bundle(conn, bundle)
    finally:
        conn.close()


def run_status(season: int, client: JolpicaClient | None = None) -> dict[str, int]:
    client = client or JolpicaClient()
    statuses = client.fetch_season_status(season)
    bundle = transform_status(statuses)
    conn = get_connection()
    try:
        return load_status_bundle(conn, bundle)
    finally:
        conn.close()


RUNNERS = {
    "results": run_results,
    "calendar": run_calendar,
    "sprint": run_sprints,
    "qualifying": run_qualifying,
    "pitstops": run_pitstops,
    "laps": run_laps,
    "standings": run_standings,
    "status": run_status,
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
