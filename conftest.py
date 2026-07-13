"""Shared pytest fixtures and env-based skip logic.

Deterministic tests (validation, transforms, API with a mocked agent) run
anywhere. Tests marked `db` need AGENT_DB_URL; tests marked `llm` need the live
agent (GROQ_API_KEY too). Missing credentials skip rather than fail.
"""

import os

import pytest
from dotenv import load_dotenv

load_dotenv()

HAVE_DB = bool(os.environ.get("AGENT_DB_URL"))
HAVE_LLM = HAVE_DB and bool(os.environ.get("GROQ_API_KEY"))


def pytest_collection_modifyitems(config, items):
    skip_db = pytest.mark.skip(reason="AGENT_DB_URL not set")
    skip_llm = pytest.mark.skip(reason="GROQ_API_KEY/AGENT_DB_URL not set")
    for item in items:
        if "llm" in item.keywords and not HAVE_LLM:
            item.add_marker(skip_llm)
        elif "db" in item.keywords and not HAVE_DB:
            item.add_marker(skip_db)


@pytest.fixture
def f1_schema() -> dict[str, set[str]]:
    """The 12-table schema as validate_sql expects it (table -> column names).

    Mirrors migration 001 so validation tests stay hermetic (no DB needed).
    """
    return {
        "circuits": {"circuit_id", "circuit_ref", "name", "location", "country", "lat", "long"},
        "drivers": {
            "driver_id", "driver_ref", "code", "given_name", "family_name", "dob", "nationality",
        },
        "constructors": {"constructor_id", "constructor_ref", "name", "nationality"},
        "races": {"race_id", "season", "round", "circuit_id", "name", "date", "time"},
        "status": {"status_id", "status"},
        "results": {
            "id", "race_id", "driver_id", "constructor_id", "grid", "position", "points",
            "status", "time_millis", "fastest_lap_rank", "fastest_lap_time",
        },
        "sprint_results": {
            "id", "race_id", "driver_id", "constructor_id", "grid", "position", "points",
            "status", "time_millis",
        },
        "qualifying_results": {
            "id", "race_id", "driver_id", "constructor_id", "position", "q1", "q2", "q3",
        },
        "pitstops": {"id", "race_id", "driver_id", "stop_number", "lap", "time", "duration"},
        "laps": {"id", "race_id", "driver_id", "lap_number", "position", "time"},
        "driver_standings": {"id", "season", "round", "driver_id", "points", "position", "wins"},
        "constructor_standings": {
            "id", "season", "round", "constructor_id", "points", "position", "wins",
        },
    }
