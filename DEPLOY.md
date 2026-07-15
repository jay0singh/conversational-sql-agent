# Deploying to Hugging Face Spaces

The app deploys as a **single Docker container**: FastAPI serves both the
`/query` API and the built React app on one origin. Hugging Face Spaces is free
and needs no credit card.

## What's in the repo for deployment

- **`Dockerfile`** — multi-stage: builds the React frontend with Node, then runs
  FastAPI (uvicorn) on `$PORT` (default `7860`, which Spaces expects) and serves
  the built `frontend/dist` alongside the API.
- **`.dockerignore`** — keeps the build context small and secrets out of it.

## Steps

1. **Create a free account** at [huggingface.co](https://huggingface.co) (no card).

2. **Create a new Space** → [huggingface.co/new-space](https://huggingface.co/new-space):
   - Name it (e.g. `f1-sql-agent`).
   - **SDK: Docker**, template **Blank**.
   - This creates a Space git repo with a `README.md` whose front-matter marks
     it as a Docker Space. **Keep that `README.md`.** If you ever need to set it
     by hand, the front-matter is:

     ```yaml
     ---
     title: F1 SQL Agent
     emoji: 🏎️
     colorFrom: red
     colorTo: gray
     sdk: docker
     app_port: 7860
     pinned: false
     ---
     ```

3. **Add the app files to the Space repo.** Clone the Space, copy in
   `Dockerfile`, `.dockerignore`, `agent/`, and `frontend/` from this project
   (do **not** copy `node_modules`, `.venv`, or `.env`), keep the Space's
   `README.md`, then commit and push:

   ```sh
   git clone https://huggingface.co/spaces/<your-user>/f1-sql-agent
   cd f1-sql-agent
   # copy Dockerfile, .dockerignore, agent/, frontend/ in here
   git add .
   git commit -m "Add F1 SQL Agent"
   git push
   ```

4. **Set secrets** in the Space → **Settings → Variables and secrets → New
   secret** (these are injected as environment variables at runtime):
   - `AGENT_DB_URL` — the read-only Supabase Session-pooler string (the
     `f1_agent_ro` one from your `.env`).
   - `GROQ_API_KEY` — your Groq key.

5. **Wait for the build.** The Space builds the Dockerfile and starts the
   container on port 7860. When status shows **Running**, the app is live at
   `https://<your-user>-f1-sql-agent.hf.space`.

## Notes

- The read-only role and 8-second statement timeout still apply in production —
  the deployed agent can only run guarded `SELECT`s. Keep the ETL's full-access
  `SUPABASE_DB_URL` **out** of the Space; the agent only needs `AGENT_DB_URL`.
- Conversation memory is in-process (`MemorySaver`), so it resets if the Space
  restarts or sleeps — fine for a demo. Swap to a Postgres-backed checkpointer
  later if you want it to persist.
- The container is host-agnostic (listens on `$PORT`), so the same image runs on
  Render, Koyeb, or anywhere that runs a Docker container.
