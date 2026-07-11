"""Backfill seasons 2010 -> current with resumable checkpointing.

    python -m etl.backfill                       # 2010 through the current year
    python -m etl.backfill --start 2010 --end 2012

After each successful (season, dataset) load, a checkpoint row is written to
etl_state; on the next run those combinations are skipped, so a failed or
interrupted backfill resumes where it stopped instead of refetching
thousands of requests. Datasets run in FK-safe order per season.
"""

from __future__ import annotations

import argparse
from datetime import date

from etl.extract import JolpicaClient
from etl.load import get_connection
from etl.pipeline import RUNNERS

FIRST_SEASON = 2010
# calendar first (full race list incl. future rounds), results second (fills
# every dimension), bare-driver-ref datasets after results; the rest are
# independent but kept in a stable, readable order.
DATASET_ORDER = [
    "calendar",
    "results",
    "sprint",
    "qualifying",
    "pitstops",
    "laps",
    "standings",
    "status",
]


def _is_done(conn, season: int, dataset: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "select 1 from etl_state where season = %s and dataset = %s",
            (season, dataset),
        )
        return cur.fetchone() is not None


def _mark_done(conn, season: int, dataset: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """insert into etl_state (season, dataset) values (%s, %s)
               on conflict (season, dataset) do update set completed_at = now()""",
            (season, dataset),
        )


def backfill(start: int, end: int) -> None:
    client = JolpicaClient()  # one shared client = one rate-limit window
    state_conn = get_connection()
    state_conn.autocommit = True  # checkpoints must survive even if a later dataset crashes
    try:
        for season in range(start, end + 1):
            for dataset in DATASET_ORDER:
                if _is_done(state_conn, season, dataset):
                    print(f"{season} {dataset}: checkpointed, skipping", flush=True)
                    continue
                counts = RUNNERS[dataset](season, client=client)
                _mark_done(state_conn, season, dataset)
                summary = ", ".join(f"{k}={v}" for k, v in counts.items())
                print(f"{season} {dataset}: {summary}", flush=True)
    finally:
        state_conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill Jolpica data season by season with checkpointing."
    )
    parser.add_argument("--start", type=int, default=FIRST_SEASON, help="first season (default 2010)")
    parser.add_argument("--end", type=int, default=date.today().year, help="last season (default: current year)")
    args = parser.parse_args()
    backfill(args.start, args.end)


if __name__ == "__main__":
    main()
