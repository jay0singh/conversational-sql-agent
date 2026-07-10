"""Run ETL pipelines end to end.

Currently supports the race-results slice for one season:

    python -m etl.pipeline --season 2024

backfill.py and incremental.py (later features) call the same functions.
"""

from __future__ import annotations

import argparse

from etl.extract import JolpicaClient
from etl.load import get_connection, load_results_bundle
from etl.transform import transform_results


def run_results(season: int, client: JolpicaClient | None = None) -> dict[str, int]:
    client = client or JolpicaClient()
    races = client.fetch_season_results(season)
    bundle = transform_results(races)
    conn = get_connection()
    try:
        return load_results_bundle(conn, bundle)
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Load one season's race results into Supabase.")
    parser.add_argument("--season", type=int, required=True, help="e.g. 2024")
    args = parser.parse_args()
    counts = run_results(args.season)
    print(f"season {args.season} upserted: " + ", ".join(f"{k}={v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
