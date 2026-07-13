# F1 Conversational SQL Agent

A chat interface where users ask natural-language questions about Formula 1 race
data and get back the generated SQL query plus its results.

## Architecture

```
Jolpica F1 API ──▶ Python ETL (GitHub Actions cron) ──▶ Supabase (Postgres)
                                                             │
                React chat UI ◀── LangGraph NL→SQL agent ◀──┘
```

- **Data source:** [Jolpica F1 API](https://api.jolpi.ca/ergast/f1/) — free,
  Ergast-compatible REST API. No auth; rate limited to ~500 requests/hour, so
  the extractor uses backoff and retries.
- **Database:** Supabase Postgres, normalized into 12 tables (see
  [`supabase/migrations/001_initial_schema.sql`](supabase/migrations/001_initial_schema.sql)).
- **ETL:** Python, run by GitHub Actions — a manual backfill workflow and a
  weekly incremental sync after each Grand Prix.
- **Agent:** LangGraph pipeline that turns questions into SQL against the schema.
- **Frontend:** React chat UI.

## Data scope

- Seasons **2010 → current**, synced weekly.
- Expected coverage gaps (by design, not bugs):
  - `pitstops` — data exists from **2011** onward.
  - `sprint_results` — sprints exist from **2021** onward, selected rounds only.

## Getting started

1. Create a Supabase project.
2. Apply the migrations in [`supabase/migrations/`](supabase/migrations/) in
   numeric order (001 schema, 002 ETL checkpoints) — paste into the Supabase
   SQL editor, or `supabase db push` with the CLI.
3. Install dependencies and configure the connection:

   ```sh
   pip install -r requirements.txt
   cp .env.example .env   # then fill in your Session-pooler connection string
   ```

4. Load everything (2010 → current season):

   ```sh
   python -m etl.backfill
   ```

   This is a multi-hour job (thousands of rate-limited API requests). Progress
   is checkpointed per (season, dataset) in `etl_state`, so interrupting and
   re-running resumes where it stopped. Narrow the range with
   `--start`/`--end`.

   After each Grand Prix, sync just the latest round (~22 requests):

   ```sh
   python -m etl.incremental
   ```

   Then gate on data quality (exit 1 turns CI red):

   ```sh
   python -m etl.quality
   ```

5. Or load one season × dataset at a time:

   ```sh
   python -m etl.pipeline --season 2024                      # race results
   python -m etl.pipeline --season 2026 --dataset calendar   # full schedule, incl. future races
   python -m etl.pipeline --season 2024 --dataset sprint     # sprint results (2021+ only)
   python -m etl.pipeline --season 2024 --dataset qualifying # qualifying with Q1/Q2/Q3
   python -m etl.pipeline --season 2024 --dataset pitstops   # pit stops (2011+; load results first)
   python -m etl.pipeline --season 2024 --dataset laps       # lap times (~300 requests, takes minutes)
   python -m etl.pipeline --season 2024 --dataset standings  # driver + constructor standings per round
   python -m etl.pipeline --season 2024 --dataset status     # finishing-status lookup
   ```

   Re-running is safe — every load is an idempotent upsert on natural keys.

## Automation

- **Weekly sync** ([`weekly_sync.yml`](.github/workflows/weekly_sync.yml)) —
  every Monday 06:00 UTC: loads the latest completed round (~22 API requests),
  then runs the quality gate. Cron fires from the default branch; manual runs
  via the Actions tab.
- **Backfill** ([`backfill.yml`](.github/workflows/backfill.yml)) — manual
  dispatch with an optional season range. A full 2010→current sweep exceeds
  GitHub's 6-hour job limit, so dispatch it repeatedly — every run resumes
  from `etl_state` checkpoints.
- Both need the `SUPABASE_DB_URL` repository secret (Session-pooler string).

## Agent (NL -> SQL)

A LangGraph pipeline turns natural-language F1 questions into validated,
read-only SQL and a plain-English answer:

```
intake -> schema context -> generate SQL <-> validate <-> execute -> format answer
          (Groq LLM)         (SELECT-only, LIMIT cap, ref-check)  (read-only role, 8s timeout)
```

- Self-corrects on validation/execution errors (up to 3 attempts), then fails
  gracefully. Thread-level memory resolves follow-ups ("what about 2022?").
- Setup: `pip install -r agent/requirements.txt`, add `GROQ_API_KEY` and
  `AGENT_DB_URL` to `.env` (see `.env.example`).
- CLI: `python -m agent.graph "Who won the 2021 drivers' championship?"`
- API: `uvicorn agent.api:app` — `POST /query {question, thread_id}` streams
  progress + result as Server-Sent Events.

## Roadmap

- [x] 1. Repo scaffolding + Supabase schema migration
- [x] 2. Vertical slice for `results`: extract → transform → load
- [x] 3. Dimension tables: drivers, constructors, circuits, races (+ season calendar fetch)
- [x] 4. `sprint_results`
- [x] 5. `qualifying_results`
- [x] 6. `pitstops`
- [x] 7. `laps`
- [x] 8. `driver_standings` + `constructor_standings`
- [x] 9. `status` lookup
- [x] 10. Backfill with checkpointing (`etl_state`)
- [x] 11. Weekly incremental sync
- [x] 12. Post-load data quality checks
- [x] 13. GitHub Actions workflows
