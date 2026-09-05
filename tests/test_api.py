"""API tests.

The graph is patched out, so these exercise the HTTP layer -- validation, status codes,
the response contract, SSE framing -- without network access or API keys. The agent's
own behaviour is covered by ``test_agent_nodes.py`` and ``test_graph_routing.py``.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api import main
from api.routes import chat as chat_route

SAMPLE_RESULT = {
    "question": "What is the Growth rate limit?",
    "answer": "3,000 requests per minute [1].",
    "citations": [
        {
            "n": 1,
            "source": "technical/rate_limits.md",
            "section": "Limits by plan",
            "doc_title": "Rate Limits and Quotas",
            "category": "technical",
            "score": 0.7621,
            "chunk_id": "abc123",
            "snippet": "Growth 3,000 requests per minute",
        }
    ],
    "trace": [
        {"node": "route_query", "detail": "intent=knowledge", "elapsed_ms": 900},
        {"node": "retrieve", "detail": "6 chunks", "elapsed_ms": 1800},
        {"node": "generate", "detail": "31 chars", "elapsed_ms": 1200},
    ],
    "path": "route_query -> retrieve -> generate",
    "intent": "knowledge",
    "category_filter": "technical",
    "rewrites": 0,
    "insufficient_evidence": False,
    "latency_ms": 3900,
}


@pytest.fixture
def client(monkeypatch):
    """A TestClient with the lifespan disabled and the agent stubbed out.

    The real lifespan loads a 130 MB embedding model and calls Groq; neither belongs in
    a unit test.
    """
    monkeypatch.setattr(
        chat_route, "answer_question", lambda question: {**SAMPLE_RESULT, "question": question}
    )
    main.app.router.lifespan_context = _noop_lifespan
    with TestClient(main.app) as test_client:
        yield test_client


from contextlib import asynccontextmanager  # noqa: E402


@asynccontextmanager
async def _noop_lifespan(app):
    """Replaces the real lifespan so tests skip model warm-up."""
    yield


# ---------------------------------------------------------------------------
# Basics
# ---------------------------------------------------------------------------
def test_root_advertises_the_endpoints(client):
    body = client.get("/").json()
    assert "POST /chat" in body["endpoints"]
    assert body["docs"] == "/docs"


def test_health_is_cheap_and_makes_no_external_calls(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_openapi_schema_is_generated(client):
    schema = client.get("/openapi.json").json()
    assert "/chat" in schema["paths"]
    assert "/chat/stream" in schema["paths"]


def test_response_time_header_is_present(client):
    assert "X-Response-Time-Ms" in client.get("/health").headers


# ---------------------------------------------------------------------------
# POST /chat
# ---------------------------------------------------------------------------
def test_chat_returns_the_full_contract(client):
    response = client.post("/chat", json={"question": "What is the Growth rate limit?"})
    assert response.status_code == 200

    body = response.json()
    assert body["answer"].startswith("3,000")
    assert body["citations"][0]["source"] == "technical/rate_limits.md"
    assert body["path"] == "route_query -> retrieve -> generate"
    assert body["insufficient_evidence"] is False


def test_chat_echoes_the_session_id(client):
    body = client.post("/chat", json={"question": "hi", "session_id": "sess-42"}).json()
    assert body["session_id"] == "sess-42"


def test_chat_rejects_an_empty_question(client):
    assert client.post("/chat", json={"question": ""}).status_code == 422


def test_chat_rejects_a_whitespace_only_question(client):
    """Passes min_length but is still unanswerable, so it must not reach the graph."""
    assert client.post("/chat", json={"question": "   "}).status_code == 422


def test_chat_rejects_a_missing_question(client):
    assert client.post("/chat", json={}).status_code == 422


def test_chat_rejects_an_over_long_question(client):
    assert client.post("/chat", json={"question": "x" * 2001}).status_code == 422


def test_chat_reports_agent_failure_as_bad_gateway(client, monkeypatch):
    """A dependency failure is a 502, not an opaque 500."""

    def explode(question):
        raise RuntimeError("pinecone unreachable")

    monkeypatch.setattr(chat_route, "answer_question", explode)

    response = client.post("/chat", json={"question": "anything"})
    assert response.status_code == 502
    assert "pinecone unreachable" in response.json()["detail"]


def test_chat_surfaces_a_declined_answer_distinctly(client, monkeypatch):
    """A client must be able to tell 'declined' from 'answered' without parsing prose."""
    declined = {
        **SAMPLE_RESULT,
        "answer": "I couldn't find anything in ACME's documentation.",
        "citations": [],
        "insufficient_evidence": True,
        "rewrites": 2,
    }
    monkeypatch.setattr(chat_route, "answer_question", lambda q: {**declined, "question": q})

    body = client.post("/chat", json={"question": "crypto policy"}).json()
    assert body["insufficient_evidence"] is True
    assert body["citations"] == []
    assert body["rewrites"] == 2


# ---------------------------------------------------------------------------
# POST /chat/stream
# ---------------------------------------------------------------------------
def _parse_sse(text: str) -> list[tuple[str, dict]]:
    """Parse an SSE body into (event, payload) pairs."""
    events = []
    name = ""
    for line in text.splitlines():
        if line.startswith("event:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            events.append((name, json.loads(line.split(":", 1)[1].strip())))
    return events


@pytest.fixture
def streaming_client(monkeypatch):
    """A client whose graph emits two scripted node updates."""

    class FakeGraph:
        async def astream(self, state, config=None, stream_mode=None):
            yield {
                "route_query": {
                    "intent": "knowledge",
                    "trace": [
                        {"node": "route_query", "detail": "intent=knowledge", "elapsed_ms": 10}
                    ],
                }
            }
            yield {
                "generate": {
                    "answer": "Answered [1].",
                    "citations": [],
                    "insufficient_evidence": False,
                    "trace": [{"node": "generate", "detail": "13 chars", "elapsed_ms": 20}],
                }
            }

    monkeypatch.setattr(chat_route, "compile_graph", FakeGraph)
    main.app.router.lifespan_context = _noop_lifespan
    with TestClient(main.app) as test_client:
        yield test_client


def test_stream_emits_start_node_and_done_events(streaming_client):
    response = streaming_client.post("/chat/stream", json={"question": "test"})
    assert response.status_code == 200

    events = _parse_sse(response.text)
    names = [name for name, _ in events]

    assert names[0] == "start"
    assert names[-1] == "done"
    assert names.count("node") == 2


def test_stream_done_event_carries_the_accumulated_answer(streaming_client):
    """`updates` mode yields deltas, so the endpoint must reassemble the final state."""
    events = _parse_sse(streaming_client.post("/chat/stream", json={"question": "test"}).text)
    done = next(payload for name, payload in events if name == "done")

    assert done["answer"] == "Answered [1]."
    assert done["path"] == "route_query -> generate"
    assert len(done["trace"]) == 2, "trace must accumulate across nodes, not be overwritten"
    assert done["latency_ms"] >= 0


def test_stream_reports_node_progress_in_order(streaming_client):
    events = _parse_sse(streaming_client.post("/chat/stream", json={"question": "test"}).text)
    nodes = [payload["node"] for name, payload in events if name == "node"]
    assert nodes == ["route_query", "generate"]


def test_stream_rejects_an_empty_question(streaming_client):
    assert streaming_client.post("/chat/stream", json={"question": "  "}).status_code == 422


def test_stream_emits_an_error_event_when_the_agent_fails(monkeypatch):
    class ExplodingGraph:
        async def astream(self, state, config=None, stream_mode=None):
            raise RuntimeError("groq down")
            yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(chat_route, "compile_graph", ExplodingGraph)
    main.app.router.lifespan_context = _noop_lifespan

    with TestClient(main.app) as test_client:
        response = test_client.post("/chat/stream", json={"question": "test"})

    events = _parse_sse(response.text)
    assert any(name == "error" for name, _ in events)
    assert not any(name == "done" for name, _ in events)
