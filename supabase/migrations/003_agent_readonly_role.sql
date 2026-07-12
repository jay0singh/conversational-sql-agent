-- 003_agent_readonly_role.sql
-- Read-only role for the NL->SQL agent. The agent executes LLM-generated
-- queries, so it gets the least privilege that still answers questions:
-- SELECT on the 12 F1 data tables and nothing else. etl_state is deliberately
-- not granted — under this role it does not even appear in information_schema,
-- so schema introspection can't leak it into prompts.
--
-- The password is intentionally NOT in this file (it is committed to a public
-- repo). Set it at apply time:  alter role f1_agent_ro password '...';

begin;

do $$
begin
    if not exists (select from pg_roles where rolname = 'f1_agent_ro') then
        create role f1_agent_ro login;
    end if;
end
$$;

-- Hard backstop under the application-level timeout: no statement run by
-- this role may exceed 8 seconds, no matter what the caller forgets.
alter role f1_agent_ro set statement_timeout = '8s';

grant usage on schema public to f1_agent_ro;

grant select on
    circuits,
    drivers,
    constructors,
    races,
    status,
    results,
    sprint_results,
    qualifying_results,
    pitstops,
    laps,
    driver_standings,
    constructor_standings
to f1_agent_ro;

commit;
