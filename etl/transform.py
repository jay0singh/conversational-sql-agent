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


def transform_results(races: list[dict]) -> dict[str, list[dict]]:
    """Flatten a season's merged race-results JSON into table row sets."""
    circuits: dict[str, dict] = {}
    drivers: dict[str, dict] = {}
    constructors: dict[str, dict] = {}
    race_rows: list[dict] = []
    result_rows: list[dict] = []

    for race in races:
        circuit = race["Circuit"]
        circuits[circuit["circuitId"]] = {
            "circuit_id": circuit["circuitId"],
            "name": circuit["circuitName"],
            "location": circuit.get("Location", {}).get("locality"),
            "country": circuit.get("Location", {}).get("country"),
            "lat": float(circuit["Location"]["lat"]) if circuit.get("Location", {}).get("lat") else None,
            "long": float(circuit["Location"]["long"]) if circuit.get("Location", {}).get("long") else None,
        }
        season, round_no = int(race["season"]), int(race["round"])
        race_rows.append(
            {
                "season": season,
                "round": round_no,
                "circuit_id": circuit["circuitId"],
                "name": race["raceName"],
                "date": race["date"],
                "time": _time(race.get("time")),
            }
        )
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
