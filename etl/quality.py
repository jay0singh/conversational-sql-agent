"""Post-load data quality checks — fail loudly so CI turns red.

    python -m etl.quality

Two kinds of checks:

1. Violation checks (always run): soft foreign keys that Postgres can't
   enforce, malformed or non-positive time values, and races with
   implausibly few results.
2. Completeness checks (scoped by etl_state): for every (season, dataset)
   the backfill has checkpointed as done, every already-raced round must
   have rows — a checkpointed season missing data is a hard failure, while
   a season that was never backfilled raises no alarm.

Exit code 0 when everything passes, 1 with a printed report otherwise.
Run this right after a backfill or incremental sync (the workflows do).
"""

from __future__ import annotations

import sys

from etl.load import get_connection

# name -> SQL returning a single violation count (0 = pass)
VIOLATION_CHECKS: dict[str, str] = {
    "results.status text missing from status lookup": """
        select count(*) from results
        where status is not null and status not in (select status from status)
    """,
    "driver_standings rows without a matching race": """
        select count(*) from driver_standings s
        where not exists (
            select 1 from races r where r.season = s.season and r.round = s.round
        )
    """,
    "constructor_standings rows without a matching race": """
        select count(*) from constructor_standings s
        where not exists (
            select 1 from races r where r.season = s.season and r.round = s.round
        )
    """,
    "non-positive pit stop durations": """
        select count(*) from pitstops
        where duration ~ '^[0-9]+(\\.[0-9]+)?$' and duration::numeric <= 0
    """,
    # Lap times come in three real shapes: 'SS.mmm' (sub-minute laps, e.g.
    # Sakhir 2020 outer loop), 'M:SS.mmm' (normal), and 'H:MM:SS.mmm' (laps
    # spanning a red-flag stoppage, e.g. Canada 2011 lap 25).
    "malformed lap times": """
        select count(*) from laps
        where time is not null
          and time !~ '^(([0-9]+:)?[0-9]{1,2}:)?[0-9]{1,2}\\.[0-9]{3}$'
    """,
    "negative points in results": "select count(*) from results where points < 0",
    "non-positive race times (time_millis)": """
        select count(*) from results where time_millis is not null and time_millis <= 0
    """,
    "races with implausibly few results (< 15)": """
        select count(*) from (
            select res.race_id from results res group by res.race_id having count(*) < 15
        ) thin
    """,
}

# checkpointed dataset -> fact table whose per-race coverage it promises
COMPLETENESS = {
    "results": "results",
    "qualifying": "qualifying_results",
    "laps": "laps",
    "pitstops": "pitstops",  # pit-stop data only exists from 2011 onward
}


def run_checks() -> int:
    failures: list[str] = []
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            for name, sql in VIOLATION_CHECKS.items():
                cur.execute(sql)
                violations = cur.fetchone()[0]
                status = "ok" if violations == 0 else f"FAIL ({violations} rows)"
                print(f"  {name}: {status}", flush=True)
                if violations:
                    failures.append(f"{name}: {violations} rows")

            for dataset, table in COMPLETENESS.items():
                # For pitstops, a raced round only *owes* stops if the race ran
                # a real distance: races of <= 5 laps (Spa 2021 ran 1 lap
                # behind the safety car) legitimately have none. The lap-count
                # filter applies only when laps data exists for the season, so
                # a pitstops-before-laps gate run stays lenient, not wrong.
                if dataset == "pitstops":
                    raced_sql = """
                        select count(*) from races r
                        where r.season = es.season and r.date < current_date
                          and (
                            not exists (
                              select 1 from laps l join races r2 on r2.race_id = l.race_id
                              where r2.season = es.season)
                            or (select coalesce(max(l.lap_number), 0) from laps l
                                 where l.race_id = r.race_id) > 5
                          )
                    """
                else:
                    raced_sql = """
                        select count(*) from races r
                        where r.season = es.season and r.date < current_date
                    """
                cur.execute(
                    f"""
                    select es.season,
                           ({raced_sql}) as raced,
                           (select count(distinct t.race_id) from {table} t
                             join races r on r.race_id = t.race_id
                             where r.season = es.season) as covered
                    from etl_state es
                    where es.dataset = %s and (%s != 'pitstops' or es.season >= 2011)
                    order by es.season
                    """,
                    (dataset, dataset),
                )
                for season, raced, covered in cur.fetchall():
                    if raced != covered:
                        print(
                            f"  {dataset} completeness {season}: FAIL "
                            f"({covered}/{raced} raced rounds covered)",
                            flush=True,
                        )
                        failures.append(
                            f"{dataset} {season}: {covered}/{raced} raced rounds covered"
                        )
                    else:
                        print(
                            f"  {dataset} completeness {season}: ok ({covered}/{raced})",
                            flush=True,
                        )
    finally:
        conn.close()

    if failures:
        print(f"\nQUALITY CHECKS FAILED ({len(failures)}):", flush=True)
        for failure in failures:
            print(f"  - {failure}", flush=True)
        return 1
    print("\nall quality checks passed", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(run_checks())
