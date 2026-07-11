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
2. Apply the schema: paste
   `supabase/migrations/001_initial_schema.sql` into the Supabase SQL editor
   (or `supabase db push` with the CLI).
3. Install dependencies and configure the connection:

   ```sh
   pip install -r requirements.txt
   cp .env.example .env   # then fill in your Session-pooler connection string
   ```

4. Load data:

   ```sh
   python -m etl.pipeline --season 2024                      # race results
   python -m etl.pipeline --season 2026 --dataset calendar   # full schedule, incl. future races
   python -m etl.pipeline --season 2024 --dataset sprint     # sprint results (2021+ only)
   python -m etl.pipeline --season 2024 --dataset qualifying # qualifying with Q1/Q2/Q3
   python -m etl.pipeline --season 2024 --dataset pitstops   # pit stops (2011+; load results first)
   ```

   Re-running is safe — every load is an idempotent upsert on natural keys.

## Roadmap

- [x] 1. Repo scaffolding + Supabase schema migration
- [x] 2. Vertical slice for `results`: extract → transform → load
- [x] 3. Dimension tables: drivers, constructors, circuits, races (+ season calendar fetch)
- [x] 4. `sprint_results`
- [x] 5. `qualifying_results`
- [x] 6. `pitstops`
- [ ] 7. `laps`
- [ ] 8. `driver_standings` + `constructor_standings`
- [ ] 9. `status` lookup
- [ ] 10. Backfill with checkpointing (`etl_state`)
- [ ] 11. Weekly incremental sync
- [ ] 12. Post-load data quality checks
- [ ] 13. GitHub Actions workflows
