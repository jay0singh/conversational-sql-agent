-- 001_initial_schema.sql
-- F1 Conversational SQL Agent — initial schema.
--
-- Source: Jolpica F1 API (Ergast-compatible). Coverage: seasons 2010+.
-- Jolpica's stable string identifiers (driverId 'hamilton', constructorId
-- 'mercedes', circuitId 'monza') are used directly as primary keys so ETL
-- upserts can target ON CONFLICT on natural keys and stay idempotent.
-- Fact tables get a surrogate identity PK plus a UNIQUE natural key.
--
-- Apply via the Supabase SQL editor, or `supabase db push` with the CLI.

begin;

-- ── Dimension tables ────────────────────────────────────────────────────────

create table if not exists circuits (
    circuit_id text primary key,
    name       text not null,
    location   text,
    country    text,
    lat        double precision,
    long       double precision
);

create table if not exists drivers (
    driver_id   text primary key,
    code        text,  -- three-letter broadcast code; null for a few drivers
    given_name  text not null,
    family_name text not null,
    dob         date,
    nationality text
);

create table if not exists constructors (
    constructor_id text primary key,
    name           text not null,
    nationality    text
);

create table if not exists races (
    race_id    bigint generated always as identity primary key,
    season     integer not null,
    round      integer not null,
    circuit_id text    not null references circuits (circuit_id),
    name       text    not null,
    date       date    not null,
    time       time,  -- null when the API provides no start time
    unique (season, round)
);

create table if not exists status (
    status_id integer primary key,  -- Jolpica statusId
    status    text not null
);

-- ── Fact tables ─────────────────────────────────────────────────────────────

create table if not exists results (
    id               bigint  generated always as identity primary key,
    race_id          bigint  not null references races (race_id),
    driver_id        text    not null references drivers (driver_id),
    constructor_id   text    not null references constructors (constructor_id),
    grid             integer,
    position         integer,  -- null when unclassified (DNF/DSQ have positionText only)
    points           numeric(6, 2) not null default 0,  -- numeric: half-points races exist
    status           text,
    time_millis      bigint,   -- total race time in ms; null unless classified on the lead lap
    fastest_lap_rank integer,
    fastest_lap_time text,     -- as reported, e.g. '1:27.452'
    unique (race_id, driver_id)
);

create table if not exists sprint_results (
    id             bigint  generated always as identity primary key,
    race_id        bigint  not null references races (race_id),
    driver_id      text    not null references drivers (driver_id),
    constructor_id text    not null references constructors (constructor_id),
    grid           integer,
    position       integer,
    points         numeric(6, 2) not null default 0,
    status         text,
    time_millis    bigint,
    unique (race_id, driver_id)
);

create table if not exists qualifying_results (
    id             bigint  generated always as identity primary key,
    race_id        bigint  not null references races (race_id),
    driver_id      text    not null references drivers (driver_id),
    constructor_id text    not null references constructors (constructor_id),
    position       integer,
    q1             text,  -- session times as reported, e.g. '1:26.572';
    q2             text,  -- null when the driver did not advance to the session
    q3             text,
    unique (race_id, driver_id)
);

create table if not exists pitstops (
    id          bigint  generated always as identity primary key,
    race_id     bigint  not null references races (race_id),
    driver_id   text    not null references drivers (driver_id),
    stop_number integer not null,
    lap         integer,
    time        text,  -- local clock time of the stop, e.g. '14:05:11'
    duration    text,  -- seconds as reported, e.g. '21.783' ('31:12.000' during red flags)
    unique (race_id, driver_id, stop_number)
);

create table if not exists laps (
    id         bigint  generated always as identity primary key,
    race_id    bigint  not null references races (race_id),
    driver_id  text    not null references drivers (driver_id),
    lap_number integer not null,
    position   integer,
    time       text,  -- lap time as reported, e.g. '1:29.844'
    unique (race_id, driver_id, lap_number)
);

create table if not exists driver_standings (
    id        bigint  generated always as identity primary key,
    season    integer not null,
    round     integer not null,
    driver_id text    not null references drivers (driver_id),
    points    numeric(7, 2) not null default 0,
    position  integer,
    wins      integer not null default 0,
    unique (season, round, driver_id)
);

create table if not exists constructor_standings (
    id             bigint  generated always as identity primary key,
    season         integer not null,
    round          integer not null,
    constructor_id text    not null references constructors (constructor_id),
    points         numeric(7, 2) not null default 0,
    position       integer,
    wins           integer not null default 0,
    unique (season, round, constructor_id)
);

-- ── Table comments ──────────────────────────────────────────────────────────
-- Kept in the catalog so the NL→SQL agent can later read coverage caveats
-- straight from information_schema instead of a hand-maintained prompt.

comment on table pitstops is
    'Pit stop data exists from the 2011 season onward; 2010 races have no rows by design.';
comment on table sprint_results is
    'Sprint races exist from 2021 onward and only at selected rounds; most races have no rows by design.';
comment on table status is
    'Lookup of Jolpica finishing statuses (Finished, +1 Lap, Collision, ...).';
comment on column results.time_millis is
    'Total race time in milliseconds; null for lapped or retired drivers.';

-- ── Indexes for the join paths the agent will generate ─────────────────────
-- (race_id lookups are covered by each UNIQUE constraint''s leading column.)

create index if not exists idx_results_driver         on results (driver_id);
create index if not exists idx_results_constructor    on results (constructor_id);
create index if not exists idx_sprint_driver          on sprint_results (driver_id);
create index if not exists idx_sprint_constructor     on sprint_results (constructor_id);
create index if not exists idx_qualifying_driver      on qualifying_results (driver_id);
create index if not exists idx_qualifying_constructor on qualifying_results (constructor_id);
create index if not exists idx_pitstops_driver        on pitstops (driver_id);
create index if not exists idx_laps_driver            on laps (driver_id);
create index if not exists idx_races_circuit          on races (circuit_id);
create index if not exists idx_driver_standings_drv   on driver_standings (driver_id);
create index if not exists idx_constructor_standings_con on constructor_standings (constructor_id);

commit;
