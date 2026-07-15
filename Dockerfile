# Single-service image: FastAPI serves the /query API and the built React app.
# Host-agnostic — listens on $PORT (hosts like Render/Koyeb inject it; falls
# back to 8080). Multi-stage so Node is only used to build the frontend and is
# discarded from the final image.

# --- Stage 1: build the React frontend ---
FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Stage 2: Python runtime ---
FROM python:3.12-slim
WORKDIR /app

COPY agent/requirements.txt agent/requirements.txt
RUN pip install --no-cache-dir -r agent/requirements.txt

COPY agent/ agent/
COPY --from=frontend /app/frontend/dist frontend/dist

ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "uvicorn agent.api:app --host 0.0.0.0 --port ${PORT:-8080}"]
