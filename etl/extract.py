"""Jolpica F1 API client: pagination, rate limiting, and retry with backoff.

Jolpica (https://api.jolpi.ca/ergast/f1/) is an Ergast-compatible REST API.
Unauthenticated limits: 4 requests/second burst and 500 requests/hour
sustained; exceeding either returns HTTP 429. Responses are paginated with
limit/offset, and `limit` maxes out at 100 (not Ergast's historical 1000).
"""

from __future__ import annotations

import time
from collections import deque
from datetime import date

import requests

BASE_URL = "https://api.jolpi.ca/ergast/f1"
PAGE_SIZE = 100  # Jolpica's documented maximum
HOURLY_BUDGET = 450  # headroom under the 500/hour cap
BURST_INTERVAL = 0.3  # seconds between requests, under the 4/s burst limit
MAX_RETRIES = 5  # network errors / 5xx
# 429s are not failures — they mean "the hourly window is spent" (possibly by
# another process sharing our IP, which our own sliding window can't see).
# Waiting is always eventually correct, so be patient: 20 waits with a 60s
# floor and 300s cap rides out even a fully burned window (~70 min total).
MAX_THROTTLE_WAITS = 20


class JolpicaError(RuntimeError):
    """The API kept failing after all retries."""


class JolpicaClient:
    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = (
            "conversational-sql-agent ETL "
            "(https://github.com/jay0singh/conversational-sql-agent)"
        )
        self._request_times: deque[float] = deque()

    def _respect_rate_limits(self) -> None:
        now = time.monotonic()
        while self._request_times and now - self._request_times[0] > 3600:
            self._request_times.popleft()
        if len(self._request_times) >= HOURLY_BUDGET:
            # Sliding-window budget spent: wait until the oldest request ages out.
            time.sleep(3600 - (now - self._request_times[0]) + 1)
        elif self._request_times and now - self._request_times[-1] < BURST_INTERVAL:
            time.sleep(BURST_INTERVAL - (now - self._request_times[-1]))

    def get_page(self, path: str, offset: int = 0, limit: int = PAGE_SIZE) -> dict:
        """GET one page of `path` and return the MRData envelope.

        Failure handling is two-track: network errors and 5xx are genuine
        failures retried MAX_RETRIES times with exponential backoff, while
        429s are patient waits (Retry-After honoured, 60s floor, 300s cap,
        up to MAX_THROTTLE_WAITS) since a spent rate window always frees up.
        Other 4xx are bugs in our request and raise immediately.
        """
        url = f"{BASE_URL}/{path}.json"
        backoff = 2.0
        failures = 0
        throttles = 0
        while True:
            self._respect_rate_limits()
            self._request_times.append(time.monotonic())
            try:
                resp = self.session.get(
                    url, params={"limit": limit, "offset": offset}, timeout=30
                )
            except requests.RequestException:
                failures += 1
                if failures >= MAX_RETRIES:
                    raise JolpicaError(
                        f"{url} (offset={offset}): {failures} network failures"
                    )
                time.sleep(backoff)
                backoff *= 2
                continue
            if resp.status_code == 200:
                return resp.json()["MRData"]
            if resp.status_code == 429:
                throttles += 1
                if throttles >= MAX_THROTTLE_WAITS:
                    raise JolpicaError(
                        f"{url} (offset={offset}): still throttled after {throttles} waits"
                    )
                retry_after = float(resp.headers.get("Retry-After") or 0)
                time.sleep(max(retry_after, min(backoff, 300.0), 60.0))
                backoff = min(backoff * 2, 300.0)
                continue
            if resp.status_code >= 500:
                failures += 1
                if failures >= MAX_RETRIES:
                    raise JolpicaError(
                        f"{url} (offset={offset}): {failures} server errors"
                    )
                time.sleep(max(float(resp.headers.get("Retry-After") or 0), backoff))
                backoff *= 2
                continue
            resp.raise_for_status()

    def fetch_season_calendar(self, season: int | str) -> list[dict]:
        """Return every race on a season's calendar, raced or not.

        Unlike /results, the leaf item here is the race itself (no Results
        arrays to merge) — pages just concatenate.
        """
        races: list[dict] = []
        offset = 0
        while True:
            data = self.get_page(str(season), offset=offset)
            races.extend(data["RaceTable"]["Races"])
            offset += int(data["limit"])
            if offset >= int(data["total"]):
                return races

    def _fetch_season_races(self, path: str, results_key: str) -> list[dict]:
        """Fetch a per-race results endpoint, merging paginated races by round.

        Pagination counts individual result rows, so one race's list can span
        page boundaries; `results_key` names the per-race list to merge
        ('Results', 'SprintResults', ...).
        """
        races_by_round: dict[int, dict] = {}
        offset = 0
        while True:
            data = self.get_page(path, offset=offset)
            for race in data["RaceTable"]["Races"]:
                round_no = int(race["round"])
                if round_no in races_by_round:
                    races_by_round[round_no].setdefault(results_key, []).extend(
                        race.get(results_key, [])
                    )
                else:
                    races_by_round[round_no] = race
            offset += int(data["limit"])
            if offset >= int(data["total"]):
                return [races_by_round[r] for r in sorted(races_by_round)]

    def fetch_season_results(self, season: int | str) -> list[dict]:
        """All races of a season with their complete Results lists."""
        return self._fetch_season_races(f"{season}/results", "Results")

    def fetch_season_sprints(self, season: int | str) -> list[dict]:
        """Sprint races of a season with their SprintResults lists.

        Sprints exist from 2021 onward at selected rounds only; earlier
        seasons legitimately return an empty list.
        """
        return self._fetch_season_races(f"{season}/sprint", "SprintResults")

    def fetch_season_qualifying(self, season: int | str) -> list[dict]:
        """All races of a season with their QualifyingResults lists."""
        return self._fetch_season_races(f"{season}/qualifying", "QualifyingResults")

    def fetch_season_laps(self, season: int | str) -> list[dict]:
        """Lap-by-lap timings for every already-raced round of a season.

        Served per round only, and by far the largest dataset: pagination
        counts individual timing entries (~1,200 per race), so a round costs
        ~13 pages and a season ~300 requests — the rate limiter does real
        work here. A lap whose Timings split across a page boundary shows up
        as two partial Lap entries; that's fine, because transform emits one
        row per timing and the upsert key de-duplicates.
        """
        today = date.today().isoformat()
        raced = [r for r in self.fetch_season_calendar(season) if r["date"] <= today]
        races: list[dict] = []
        for race in raced:
            races.extend(
                self._fetch_season_races(f"{season}/{race['round']}/laps", "Laps")
            )
        return races

    def _fetch_round_standings(
        self, season: int | str, round_no: int | str, endpoint: str, list_key: str
    ) -> dict | None:
        """One round's StandingsList, merging pages (rarely more than one)."""
        merged: dict | None = None
        offset = 0
        while True:
            data = self.get_page(f"{season}/{round_no}/{endpoint}", offset=offset)
            for standings_list in data["StandingsTable"]["StandingsLists"]:
                if merged is None:
                    merged = standings_list
                else:
                    merged.setdefault(list_key, []).extend(standings_list.get(list_key, []))
            offset += int(data["limit"])
            if offset >= int(data["total"]):
                return merged

    def fetch_season_standings(self, season: int | str) -> tuple[list[dict], list[dict]]:
        """Per-round driver and constructor standings for raced rounds.

        Returns (driver_standings_lists, constructor_standings_lists), each a
        list of StandingsList dicts carrying season/round. Standings entries
        embed full Driver/Constructor objects, so these bundles self-populate
        their dimension tables. ~2 requests per raced round.
        """
        today = date.today().isoformat()
        raced = [r for r in self.fetch_season_calendar(season) if r["date"] <= today]
        driver_lists: list[dict] = []
        constructor_lists: list[dict] = []
        for race in raced:
            drivers = self._fetch_round_standings(
                season, race["round"], "driverStandings", "DriverStandings"
            )
            if drivers:
                driver_lists.append(drivers)
            constructors = self._fetch_round_standings(
                season, race["round"], "constructorStandings", "ConstructorStandings"
            )
            if constructors:
                constructor_lists.append(constructors)
        return driver_lists, constructor_lists

    def fetch_season_status(self, season: int | str) -> list[dict]:
        """Finishing-status entries seen in a season (statusId, status, count)."""
        statuses: list[dict] = []
        offset = 0
        while True:
            data = self.get_page(f"{season}/status", offset=offset)
            statuses.extend(data["StatusTable"]["Status"])
            offset += int(data["limit"])
            if offset >= int(data["total"]):
                return statuses

    def fetch_season_pitstops(self, season: int | str) -> list[dict]:
        """Pit stops for every already-raced round of a season.

        Jolpica serves pit stops per round only, so this costs one calendar
        request plus one request per raced round (future rounds are skipped —
        they cannot have stops yet). Pit-stop items carry a bare driverId
        with no nested Driver object.
        """
        today = date.today().isoformat()
        raced = [r for r in self.fetch_season_calendar(season) if r["date"] <= today]
        races: list[dict] = []
        for race in raced:
            merged = self._fetch_season_races(
                f"{season}/{race['round']}/pitstops", "PitStops"
            )
            races.extend(merged)  # zero or one race per round
        return races
