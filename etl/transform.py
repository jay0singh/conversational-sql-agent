"""Pure flattening functions: nested Jolpica JSON -> normalized row dicts.

No I/O in this module. Each transform takes parsed JSON from extract.py and
returns lists of plain dicts keyed by table name, with embedded Driver /
Constructor / Circuit objects de-duplicated into their own row sets so
load.py can upsert everything in FK order.
"""

from __future__ import annotations


def _int(value) -> int | None:
    return int(value) if value not in (None, "") else None


def _time(value: str | None) -> str | None:
    # Jolpica reports race start as '14:00:00Z'; Postgres `time` wants no zone.
    return value.rstrip("Z") if value else None


def _circuit_row(circuit: dict) -> dict:
    location = circuit.get("Location", {})
    return {
        "circuit_id": circuit["circuitId"],
        "name": circuit["circuitName"],
        "location": location.get("locality"),
        "country": location.get("country"),
        "lat": float(location["lat"]) if location.get("lat") else None,
        "long": float(location["long"]) if location.get("long") else None,
    }


def _race_row(race: dict) -> dict:
    return {
        "season": int(race["season"]),
        "round": int(race["round"]),
        "circuit_id": race["Circuit"]["circuitId"],
        "name": race["raceName"],
        "date": race["date"],
        "time": _time(race.get("time")),
    }


def transform_calendar(races: list[dict]) -> dict[str, list[dict]]:
    """Flatten a season-calendar response into circuits + races row sets.

    Covers races that have no results yet (future rounds), which the
    results endpoint can never surface.
    """
    circuits: dict[str, dict] = {}
    race_rows: list[dict] = []
    for race in races:
        circuits[race["Circuit"]["circuitId"]] = _circuit_row(race["Circuit"])
        race_rows.append(_race_row(race))
    return {"circuits": list(circuits.values()), "races": race_rows}


def transform_results(races: list[dict]) -> dict[str, list[dict]]:
    """Flatten a season's merged race-results JSON into table row sets."""
    circuits: dict[str, dict] = {}
    drivers: dict[str, dict] = {}
    constructors: dict[str, dict] = {}
    race_rows: list[dict] = []
    result_rows: list[dict] = []

    for race in races:
        circuits[race["Circuit"]["circuitId"]] = _circuit_row(race["Circuit"])
        race_rows.append(_race_row(race))
        season, round_no = int(race["season"]), int(race["round"])
        for result in race.get("Results", []):
            driver, constructor = result["Driver"], result["Constructor"]
            drivers[driver["driverId"]] = {
                "driver_id": driver["driverId"],
                "code": driver.get("code"),
                "given_name": driver["givenName"],
                "family_name": driver["familyName"],
                "dob": driver.get("dateOfBirth"),
                "nationality": driver.get("nationality"),
            }
            constructors[constructor["constructorId"]] = {
                "constructor_id": constructor["constructorId"],
                "name": constructor["name"],
                "nationality": constructor.get("nationality"),
            }
            fastest = result.get("FastestLap", {})
            result_rows.append(
                {
                    # season/round identify the race; load.py swaps them for race_id.
                    "season": season,
                    "round": round_no,
                    "driver_id": driver["driverId"],
                    "constructor_id": constructor["constructorId"],
                    "grid": _int(result.get("grid")),
                    "position": _int(result.get("position")),
                    "points": float(result.get("points") or 0),
                    "status": result.get("status"),
                    "time_millis": _int(result.get("Time", {}).get("millis")),
                    "fastest_lap_rank": _int(fastest.get("rank")),
                    "fastest_lap_time": fastest.get("Time", {}).get("time"),
                }
            )

    return {
        "circuits": list(circuits.values()),
        "drivers": list(drivers.values()),
        "constructors": list(constructors.values()),
        "races": race_rows,
        "results": result_rows,
    }
