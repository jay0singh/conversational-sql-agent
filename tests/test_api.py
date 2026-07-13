"""Layer 4 — the FastAPI /query endpoint.

Deterministic: the agent is mocked (agent.api.stream_answer is patched), so
these exercise the HTTP + SSE + JSON-serialization layer without a database
or the LLM.
"""

import datetime
import decimal
import json

from fastapi.testclient import TestClient

from agent import api

client = TestClient(api.app)


def frames(text: str) -> list[dict]:
    """Parse the SSE `data: {...}` frames out of a streamed response body."""
    out = []
    for block in text.split("\n\n"):
        block = block.strip()
        if block.startswith("data:"):
            out.append(json.loads(block[block.index(":") + 1:].strip()))
    return out


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_query_streams_status_then_result(monkeypatch):
    def fake(question, thread_id):
        assert question == "who won 2021?"
        yield ("stage", "generating")
        yield ("stage", "validating")
        yield ("stage", "executing")
        yield ("result", {
            "sql": "SELECT 1", "columns": ["n"], "rows": [[1]],
            "summary": "Verstappen.", "attempts": 1,
        })

    monkeypatch.setattr(api, "stream_answer", fake)
    r = client.post("/query", json={"question": "who won 2021?", "thread_id": "t1"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")

    evs = frames(r.text)
    assert [e["stage"] for e in evs if e["type"] == "status"] == [
        "generating", "validating", "executing",
    ]
    result = evs[-1]
    assert result["type"] == "result"
    assert result["summary"] == "Verstappen." and result["failure"] is False
    assert result["columns"] == ["n"] and result["rows"] == [[1]]


def test_query_empty_question_errors(monkeypatch):
    # stream_answer must not even be reached for an empty question.
    monkeypatch.setattr(api, "stream_answer", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("should not run")))
    r = client.post("/query", json={"question": "   ", "thread_id": "t"})
    evs = frames(r.text)
    assert evs and evs[-1]["type"] == "error"


def test_query_serializes_decimal_and_date(monkeypatch):
    def fake(question, thread_id):
        yield ("result", {
            "sql": "SELECT ...", "columns": ["avg", "day"],
            "rows": [[decimal.Decimal("23.66"), datetime.date(2024, 3, 2)]],
            "summary": "ok", "attempts": 1,
        })

    monkeypatch.setattr(api, "stream_answer", fake)
    r = client.post("/query", json={"question": "q", "thread_id": "t"})
    result = frames(r.text)[-1]
    # Decimal -> float, date -> ISO string, and the frame is valid JSON.
    assert result["rows"] == [[23.66, "2024-03-02"]]


def test_query_backend_error_becomes_error_frame(monkeypatch):
    def boom(question, thread_id):
        yield ("stage", "generating")
        raise RuntimeError("kaboom")

    monkeypatch.setattr(api, "stream_answer", boom)
    r = client.post("/query", json={"question": "q", "thread_id": "t"})
    evs = frames(r.text)
    assert evs[-1]["type"] == "error" and "kaboom" in evs[-1]["message"]


def test_query_generates_thread_id_when_missing(monkeypatch):
    seen = {}

    def fake(question, thread_id):
        seen["thread_id"] = thread_id
        yield ("result", {"sql": "", "columns": [], "rows": [], "summary": "x", "attempts": 0})

    monkeypatch.setattr(api, "stream_answer", fake)
    client.post("/query", json={"question": "q"})  # no thread_id
    assert seen["thread_id"]  # a uuid was generated server-side
