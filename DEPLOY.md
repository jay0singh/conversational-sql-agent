# Deploying

The app deploys as a **single Docker container**: FastAPI serves both the
`/query` API and the built React app on one origin (no CORS). The image is
host-agnostic — it listens on `$PORT` — so it runs on any Docker host. Below is
Render (simplest, free, no credit card); Koyeb is an always-on alternative.

## What's in the repo for deployment

- **`Dockerfile`** — multi-stage: builds the React frontend with Node, then runs
  FastAPI (uvicorn) on `$PORT` serving the built `frontend/dist` alongside the API.
- **`.dockerignore`** — keeps the build context small and secrets out of it.

## Render (recommended — free, no card, deploys from GitHub)

Render's free web service sleeps after ~15 min idle (≈50s cold start on the next
visit), which is fine for a demo.

1. Sign up at [render.com](https://render.com) with your GitHub account (no card
   for the free tier).
2. **New → Web Service**, connect the `conversational-sql-agent` repo, and pick
   the branch (`dev`, or merge to `main` first and use that).
3. Render detects the `Dockerfile` automatically. Set:
   - **Instance type: Free**
   - Region: nearest to you
   - (Render injects `PORT`; the Dockerfile already honours it — nothing to set.)
4. Under **Environment**, add two variables:
   - `AGENT_DB_URL` — the read-only Supabase Session-pooler string (the
     `f1_agent_ro` one from your `.env`).
   - `GROQ_API_KEY` — your Groq key.
5. **Create Web Service.** Render builds the Dockerfile and deploys; when it goes
   live the app is at `https://<name>.onrender.com`.

## Koyeb (alternative — always-on, no sleep)

Same container, no cold starts. Free instance is smaller (512 MB / 0.1 vCPU) and
Koyeb may ask for a card only if it can't verify you're human.

1. Sign up at [koyeb.com](https://www.koyeb.com).
2. **Create Web Service → GitHub**, select the repo and branch.
3. Builder: **Dockerfile**. Instance: **Free**. Add the same two environment
   variables (`AGENT_DB_URL`, `GROQ_API_KEY`) as secrets.
4. Deploy; the app is live at `https://<name>-<org>.koyeb.app`.

## Notes

- The read-only role and 8-second statement timeout still apply in production —
  the deployed agent can only run guarded `SELECT`s. Keep the ETL's full-access
  `SUPABASE_DB_URL` **out** of the deployment; the agent only needs `AGENT_DB_URL`.
- Conversation memory is in-process (`MemorySaver`), so it resets if the service
  restarts or sleeps — fine for a demo. Swap to a Postgres-backed checkpointer
  later if you want it to persist.
