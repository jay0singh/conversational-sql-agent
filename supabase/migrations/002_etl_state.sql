-- 002_etl_state.sql
-- Backfill checkpointing: one row per completed (season, dataset) load, so
-- an interrupted backfill resumes where it stopped instead of refetching
-- thousands of API requests.

begin;

create table if not exists etl_state (
    id           bigint generated always as identity primary key,
    season       integer not null,
    dataset      text not null,
    completed_at timestamptz not null default now(),
    unique (season, dataset)
);

comment on table etl_state is
    'ETL bookkeeping (backfill checkpoints) — not F1 data; the NL agent should ignore it.';

commit;
