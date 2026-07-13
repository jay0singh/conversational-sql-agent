"""Layer 1 — the validation/security boundary.

Deterministic: validate_sql takes the schema as an argument, so these run with
no database. This is the code that stands between an LLM-written query and the
database, so it gets the heaviest coverage.
"""

import pytest

from agent.validation import LIMIT_CAP, validate_sql


def ok(sql, tables):
    validated, errors = validate_sql(sql, tables)
    assert errors == [], f"unexpectedly rejected: {errors}"
    return validated


def rejected(sql, tables):
    _, errors = validate_sql(sql, tables)
    assert errors, "expected rejection but validation passed"
    return errors


# --- write / DDL statements must never pass ------------------------------------

@pytest.mark.parametrize(
    "sql",
    [
        "update drivers set code = 'X'",
        "delete from laps",
        "drop table drivers",
        "alter table drivers add column x int",
        "truncate results",
        "insert into circuits (circuit_ref, name) values ('x', 'X')",
        "create table t (id int)",
        "grant select on drivers to public",
    ],
)
def test_non_select_rejected(sql, f1_schema):
    rejected(sql, f1_schema)


def test_multi_statement_rejected(f1_schema):
    # The classic piggyback injection.
    rejected("select 1 from drivers; drop table drivers", f1_schema)


def test_unparseable_rejected(f1_schema):
    rejected("select from where banana", f1_schema)


# --- schema reference checks ---------------------------------------------------

def test_unknown_table_rejected(f1_schema):
    errors = rejected("select * from telemetry", f1_schema)
    assert any("telemetry" in e for e in errors)


def test_unknown_column_rejected(f1_schema):
    errors = rejected("select podium_count from drivers", f1_schema)
    assert any("podium_count" in e for e in errors)


def test_etl_state_invisible(f1_schema):
    # etl_state isn't in the granted schema, so it reads as an unknown table.
    rejected("select * from etl_state", f1_schema)


# --- valid queries pass, and aliases/CTEs don't false-trip ---------------------

def test_simple_select_passes(f1_schema):
    ok("select family_name from drivers", f1_schema)


def test_case_insensitive(f1_schema):
    ok("SELECT Family_Name FROM Drivers", f1_schema)


def test_alias_not_flagged(f1_schema):
    ok("select count(*) as wins from results where position = 1", f1_schema)


def test_cte_passes(f1_schema):
    ok(
        """
        with season_wins as (
            select driver_id, count(*) as wins from results
            join races on races.race_id = results.race_id
            where races.season = 2024 and results.position = 1
            group by driver_id
        )
        select d.family_name, w.wins from season_wins w
        join drivers d on d.driver_id = w.driver_id
        """,
        f1_schema,
    )


def test_union_passes(f1_schema):
    ok("select name from drivers union select name from constructors", f1_schema)


def test_join_passes(f1_schema):
    ok(
        "select d.family_name, c.name from results r "
        "join drivers d on d.driver_id = r.driver_id "
        "join constructors c on c.constructor_id = r.constructor_id",
        f1_schema,
    )


# --- LIMIT enforcement ---------------------------------------------------------

def test_limit_injected_when_absent(f1_schema):
    validated = ok("select family_name from drivers", f1_schema)
    assert f"LIMIT {LIMIT_CAP}".lower() in validated.lower()


def test_limit_clamped_when_too_large(f1_schema):
    validated = ok("select family_name from drivers limit 99999", f1_schema)
    assert f"limit {LIMIT_CAP}" in validated.lower()
    assert "99999" not in validated


def test_reasonable_limit_kept(f1_schema):
    validated = ok("select family_name from drivers limit 10", f1_schema)
    assert "limit 10" in validated.lower()
