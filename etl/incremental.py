"""Weekly incremental sync: load only the latest completed round.

    python -m etl.incremental

Asks /current/last which race finished most recently, then loads that
round's results, sprint, qualifying, pit stops, laps, and post-round
standings, plus a season calendar and status refresh — ~22 requests
instead of a season's ~400. Every load is an idempotent upsert, so
running it again after the same Grand Prix is a no-op. Intended for the
Monday-morning GitHub Actions cron.
"""

from __future__ import annotations

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


def sync_latest() -> None:
    client = JolpicaClient()
    season, round_no = client.fetch_latest_round()
    print(f"latest completed round: {season} round {round_no}", flush=True)

    conn = get_connection()
    try:
        def report(name: str, counts: dict[str, int]) -> None:
            print(f"{name}: " + ", ".join(f"{k}={v}" for k, v in counts.items()), flush=True)

        # Calendar first (guarantees the race row + catches schedule changes),
        # results second (fills dimensions for the bare-ref datasets below).
        report("calendar", load_calendar_bundle(
            conn, transform_calendar(client.fetch_season_calendar(season))))
        report("results", load_results_bundle(
            conn, transform_results(client.fetch_round_results(season, round_no))))
        report("sprint", load_sprint_bundle(
            conn, transform_sprint_results(client.fetch_round_sprints(season, round_no))))
        report("qualifying", load_qualifying_bundle(
            conn, transform_qualifying_results(client.fetch_round_qualifying(season, round_no))))
        report("pitstops", load_pitstops_bundle(
            conn, transform_pitstops(client.fetch_round_pitstops(season, round_no))))
        report("laps", load_laps_bundle(
            conn, transform_laps(client.fetch_round_laps(season, round_no))))
        report("standings", load_standings_bundle(
            conn, transform_standings(*client.fetch_round_standings(season, round_no))))
        report("status", load_status_bundle(
            conn, transform_status(client.fetch_season_status(season))))
    finally:
        conn.close()


if __name__ == "__main__":
    sync_latest()
