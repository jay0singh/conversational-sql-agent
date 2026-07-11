"""Jolpica F1 API client: pagination, rate limiting, and retry with backoff.

Jolpica (https://api.jolpi.ca/ergast/f1/) is an Ergast-compatible REST API.
Unauthenticated limits: 4 requests/second burst and 500 requests/hour
sustained; exceeding either returns HTTP 429. Responses are paginated with
limit/offset, and `limit` maxes out at 100 (not Ergast's historical 1000).
"""

from __future__ import annotations

import time
from collections import deque

import requests

BASE_URL = "https://api.jolpi.ca/ergast/f1"
PAGE_SIZE = 100  # Jolpica's documented maximum
HOURLY_BUDGET = 450  # headroom under the 500/hour cap
BURST_INTERVAL = 0.3  # seconds between requests, under the 4/s burst limit
MAX_RETRIES = 5


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

        Retries 429s and 5xx with exponential backoff (honouring Retry-After);
        other 4xx are bugs in our request and raise immediately.
        """
        url = f"{BASE_URL}/{path}.json"
        backoff = 2.0
        for _ in range(MAX_RETRIES):
            self._respect_rate_limits()
            self._request_times.append(time.monotonic())
            try:
                resp = self.session.get(
                    url, params={"limit": limit, "offset": offset}, timeout=30
                )
            except requests.RequestException:
                time.sleep(backoff)
                backoff *= 2
                continue
            if resp.status_code == 200:
                return resp.json()["MRData"]
            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = float(resp.headers.get("Retry-After") or 0)
                time.sleep(max(retry_after, backoff))
                backoff *= 2
                continue
            resp.raise_for_status()
        raise JolpicaError(f"{url} (offset={offset}) still failing after {MAX_RETRIES} attempts")

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
