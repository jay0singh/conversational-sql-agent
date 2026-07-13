"""FastAPI backend for the NL->SQL agent.

POST /query {question, thread_id} streams Server-Sent Events:
    data: {"type": "status", "stage": "generating"}
    data: {"type": "status", "stage": "validating"}
    data: {"type": "status", "stage": "executing"}
    data: {"type": "result", "sql": ..., "columns": [...], "rows": [...],
           "summary": ..., "failure": bool, "attempts": n}

Stages may repeat when the error-correction loop retries. The frontend POSTs
and reads the streamed body (EventSource is GET-only), so the data: framing is
for easy line parsing rather than strict EventSource compatibility.

    uvicorn agent.api:app --reload
"""

from __future__ import annotations

import datetime
import decimal
import json
import os
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.graph import stream_answer

load_dotenv()

app = FastAPI(title="F1 Conversational SQL Agent")

# Dev default is permissive; set CORS_ORIGINS (comma-separated) to lock down.
_origins = os.environ.get("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins],
    allow_methods=["*"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    question: str
    thread_id: str | None = None


def _json_default(value):
    """Make DB values JSON-safe: Decimal->float, date/time->ISO string."""
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.date, datetime.time, datetime.datetime)):
        return value.isoformat()
    return str(value)


def _sse(event_type: str, **payload) -> str:
    return f"data: {json.dumps({'type': event_type, **payload}, default=_json_default)}\n\n"


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/query")
def query(body: QueryRequest) -> StreamingResponse:
    question = (body.question or "").strip()
    thread_id = body.thread_id or str(uuid.uuid4())

    def events():
        if not question:
            yield _sse("error", message="Question must not be empty.")
            return
        try:
            for kind, data in stream_answer(question, thread_id):
                if kind == "stage":
                    yield _sse("status", stage=data)
                else:
                    yield _sse(
                        "result",
                        sql=data.get("sql"),
                        columns=data.get("columns") or [],
                        rows=data.get("rows") or [],
                        summary=data.get("summary"),
                        failure=bool(data.get("failure")),
                        attempts=data.get("attempts", 0),
                    )
        except Exception as exc:  # keep the stream well-formed on any backend error
            yield _sse("error", message=str(exc))

    return StreamingResponse(events(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
