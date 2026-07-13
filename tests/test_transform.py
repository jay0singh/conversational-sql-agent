"""Layer 3 — the pure transform functions.

Deterministic: no I/O. Small Jolpica-shaped fixtures in, normalized rows out.
Focus is on the tricky behaviour — de-duplication of embedded entities, null
handling, and the nested-array expansions — not every column.
"""

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


def _driver(driver_id, given, family, **extra):
    return {"driverId": driver_id, "givenName": given, "familyName": family, **extra}


def _constructor(cid, name, **extra):
    return {"constructorId": cid, "name": name, **extra}


def _circuit(cid="monza"):
    return {
        "circuitId": cid,
        "circuitName": "Autodromo Nazionale Monza",
        "Location": {"locality": "Monza", "country": "Italy", "lat": "45.6156", "long": "9.2811"},
    }


def _race(season, rnd, **extra):
    return {
        "season": str(season),
        "round": str(rnd),
        "raceName": f"Round {rnd} GP",
        "date": f"{season}-06-0{rnd}",
        "Circuit": _circuit(),
        **extra,
    }


# --- results: dedup + null handling + fastest lap ------------------------------

def test_results_dedup_and_shape():
    ham = _driver("hamilton", "Lewis", "Hamilton", code="HAM", nationality="British")
    merc = _constructor("mercedes", "Mercedes", nationality="German")
    races = [
        _race(2024, 1, Results=[
            {"position": "1", "grid": "2", "points": "25", "status": "Finished",
             "Driver": ham, "Constructor": merc,
             "Time": {"millis": "5400000", "time": "1:30:00.000"},
             "FastestLap": {"rank": "1", "Time": {"time": "1:21.000"}}},
        ]),
        _race(2024, 2, Results=[
            {"position": "1", "grid": "1", "points": "25", "status": "Finished",
             "Driver": ham, "Constructor": merc},  # same driver+team -> dedup
        ]),
    ]
    out = transform_results(races)

    # Hamilton and Mercedes appear once each despite two races.
    assert len(out["drivers"]) == 1
    assert out["drivers"][0]["driver_ref"] == "hamilton"
    assert len(out["constructors"]) == 1
    assert len(out["races"]) == 2
    assert len(out["results"]) == 2

    r0 = out["results"][0]
    assert r0["driver_ref"] == "hamilton" and r0["constructor_ref"] == "mercedes"
    assert r0["points"] == 25.0 and isinstance(r0["points"], float)
    assert r0["time_millis"] == 5400000
    assert r0["fastest_lap_rank"] == 1 and r0["fastest_lap_time"] == "1:21.000"


def test_results_null_and_default_handling():
    races = [
        _race(2024, 1, Results=[
            {"position": "", "grid": "", "points": "0", "status": "Retired",
             "Driver": _driver("x", "X", "Y"), "Constructor": _constructor("t", "T")},
        ]),
    ]
    r = transform_results(races)["results"][0]
    assert r["position"] is None  # empty string -> None
    assert r["grid"] is None
    assert r["time_millis"] is None  # no Time block
    assert r["fastest_lap_rank"] is None
    assert r["points"] == 0.0


def test_circuit_lat_long_parsed():
    c = transform_calendar([_race(2024, 1)])["circuits"][0]
    assert c["circuit_ref"] == "monza"
    assert abs(c["lat"] - 45.6156) < 1e-6 and abs(c["long"] - 9.2811) < 1e-6


def test_race_time_strips_zulu():
    r = transform_calendar([_race(2024, 1, time="13:00:00Z")])["races"][0]
    assert r["time"] == "13:00:00"


# --- calendar: races even with no results -------------------------------------

def test_calendar_includes_raceless_rounds():
    out = transform_calendar([_race(2026, 5)])  # no Results key at all
    assert len(out["races"]) == 1
    assert out["races"][0]["season"] == 2026
    assert "drivers" not in out  # calendar bundle carries no driver rows


# --- sprint: same shape, no fastest lap ---------------------------------------

def test_sprint_results():
    out = transform_sprint_results([
        _race(2024, 1, SprintResults=[
            {"position": "1", "grid": "1", "points": "8", "status": "Finished",
             "Driver": _driver("verstappen", "Max", "Verstappen"),
             "Constructor": _constructor("red_bull", "Red Bull")},
        ]),
    ])
    row = out["sprint_results"][0]
    assert row["points"] == 8.0 and "fastest_lap_rank" not in row


# --- qualifying: empty session times become None ------------------------------

def test_qualifying_null_sessions():
    out = transform_qualifying_results([
        _race(2024, 1, QualifyingResults=[
            {"position": "16", "Q1": "1:20.000", "Q2": "",
             "Driver": _driver("d", "D", "E"), "Constructor": _constructor("t", "T")},
        ]),
    ])
    q = out["qualifying_results"][0]
    assert q["q1"] == "1:20.000"
    assert q["q2"] is None  # eliminated in Q1 -> empty -> None
    assert q["q3"] is None  # absent -> None


# --- pitstops: bare driverId, no driver rows ----------------------------------

def test_pitstops_bare_ref():
    out = transform_pitstops([
        _race(2024, 1, PitStops=[
            {"driverId": "leclerc", "stop": "1", "lap": "20", "time": "14:05:00", "duration": "2.4"},
        ]),
    ])
    assert "drivers" not in out
    ps = out["pitstops"][0]
    assert ps["driver_ref"] == "leclerc" and ps["stop_number"] == 1 and ps["lap"] == 20


# --- laps: one row per timing, races deduped ----------------------------------

def test_laps_expands_timings():
    out = transform_laps([
        _race(2024, 1, Laps=[
            {"number": "1", "Timings": [
                {"driverId": "a", "position": "1", "time": "1:30.000"},
                {"driverId": "b", "position": "2", "time": "1:30.500"},
            ]},
            {"number": "2", "Timings": [
                {"driverId": "a", "position": "1", "time": "1:29.900"},
            ]},
        ]),
    ])
    assert len(out["laps"]) == 3  # 2 + 1 timings
    assert len(out["races"]) == 1
    first = out["laps"][0]
    assert first["driver_ref"] == "a" and first["lap_number"] == 1 and first["position"] == 1


# --- standings: both tables, embedded entities --------------------------------

def test_standings_both_tables():
    driver_lists = [{
        "season": "2024", "round": "24",
        "DriverStandings": [
            {"position": "1", "points": "437", "wins": "9",
             "Driver": _driver("verstappen", "Max", "Verstappen")},
        ],
    }]
    constructor_lists = [{
        "season": "2024", "round": "24",
        "ConstructorStandings": [
            {"position": "1", "points": "666", "wins": "0",
             "Constructor": _constructor("mclaren", "McLaren")},
        ],
    }]
    out = transform_standings(driver_lists, constructor_lists)
    ds = out["driver_standings"][0]
    assert ds["driver_ref"] == "verstappen" and ds["points"] == 437.0 and ds["wins"] == 9
    cs = out["constructor_standings"][0]
    assert cs["constructor_ref"] == "mclaren" and cs["points"] == 666.0
    assert len(out["drivers"]) == 1 and len(out["constructors"]) == 1


# --- status: integer key ------------------------------------------------------

def test_status_rows():
    out = transform_status([
        {"statusId": "1", "status": "Finished", "count": "100"},
        {"statusId": "31", "status": "Retired", "count": "20"},
    ])
    rows = {r["status_id"]: r["status"] for r in out["status"]}
    assert rows == {1: "Finished", 31: "Retired"}
    assert all(isinstance(r["status_id"], int) for r in out["status"])
