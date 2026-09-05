"""Chat endpoints.

``POST /chat``
    Runs the graph and returns the whole result. Declared as a normal ``def`` so
    FastAPI runs it in its threadpool -- the graph is synchronous and CPU/IO blocking,
    and running it directly on the event loop would stall every other request.

``POST /chat/stream``
    Server-sent events, one per node as it completes, then the final answer. This
    streams *the agent's progress*, not tokens, which is the more useful signal here: a
    request that rewrites its query twice takes ~30 seconds, and watching
    ``retrieve -> grade -> rewrite`` arrive live is what makes the wait legible.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from api.models import ChatRequest, ChatResponse
from src.agent.graph import _recursion_limit, answer_question, compile_graph
from src.agent.state import initial_state
from src.logging_conf import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["chat"])


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Ask a question",
    response_description="The grounded answer, its citations, and the agent's execution path.",
)
def chat(request: ChatRequest) -> ChatResponse:
    """Answer a question through the full LangGraph workflow."""
    question = request.question.strip()
    if not question:
        # 422 as a literal: starlette renamed HTTP_422_UNPROCESSABLE_ENTITY, and the
        # constant's name now differs between versions while the code never will.
        raise HTTPException(status_code=422, detail="Question cannot be empty.")

    log.info("chat_request", session_id=request.session_id, question=question[:120])

    try:
        result = answer_question(question)
    except Exception as exc:  # noqa: BLE001
        # Node-level failures are already handled inside the graph; reaching here means
        # something structural broke, so report it as a dependency failure rather than a
        # generic 500.
        log.error("chat_failed", error=str(exc), session_id=request.session_id)
        raise HTTPException(
            status_code=502, detail=f"The agent could not complete this request: {exc}"
        ) from exc

    return ChatResponse(**result, session_id=request.session_id)


def _sse(event: str, payload: dict) -> dict:
    """Build one server-sent event."""
    return {"event": event, "data": json.dumps(payload)}


async def _stream_events(question: str, session_id: str | None) -> AsyncIterator[dict]:
    """Yield one SSE per completed node, then a final ``done`` event.

    Uses ``astream`` in ``updates`` mode, which emits each node's state delta as it
    finishes. The accumulated state is rebuilt here because ``updates`` mode reports only
    the delta, and the final event needs the whole answer.
    """
    graph = compile_graph()
    started = time.perf_counter()
    accumulated: dict = {}

    yield _sse("start", {"question": question})

    try:
        async for update in graph.astream(
            initial_state(question),
            config={"recursion_limit": _recursion_limit()},
            stream_mode="updates",
        ):
            for node_name, delta in update.items():
                if not isinstance(delta, dict):
                    continue

                # `trace` uses an add-reducer in the graph; replicate that here so the
                # accumulated view matches what a non-streaming invoke would produce.
                for key, value in delta.items():
                    if key == "trace":
                        accumulated.setdefault("trace", []).extend(value)
                    else:
                        accumulated[key] = value

                entries = delta.get("trace") or []
                yield _sse(
                    "node",
                    {
                        "node": node_name,
                        "detail": entries[0]["detail"] if entries else "",
                        "elapsed_ms": entries[0]["elapsed_ms"] if entries else 0,
                    },
                )
    except Exception as exc:  # noqa: BLE001
        log.error("stream_failed", error=str(exc), session_id=session_id)
        yield _sse("error", {"error": "agent_failed", "detail": str(exc)[:300]})
        return

    latency_ms = int((time.perf_counter() - started) * 1000)
    trace = accumulated.get("trace", [])

    yield _sse(
        "done",
        {
            "question": question,
            "answer": accumulated.get("answer", ""),
            "citations": accumulated.get("citations", []),
            "trace": trace,
            "path": " -> ".join(entry["node"] for entry in trace),
            "intent": accumulated.get("intent", "knowledge"),
            "category_filter": accumulated.get("category_filter"),
            "rewrites": accumulated.get("rewrites", 0),
            "insufficient_evidence": accumulated.get("insufficient_evidence", False),
            "latency_ms": latency_ms,
            "session_id": session_id,
        },
    )


@router.post(
    "/chat/stream",
    summary="Ask a question, streaming the agent's progress",
    response_description="text/event-stream: a 'start' event, one 'node' event per step, then 'done'.",
)
async def chat_stream(request: ChatRequest) -> EventSourceResponse:
    """Stream node-by-node progress, then the final answer."""
    question = request.question.strip()
    if not question:
        # 422 as a literal: starlette renamed HTTP_422_UNPROCESSABLE_ENTITY, and the
        # constant's name now differs between versions while the code never will.
        raise HTTPException(status_code=422, detail="Question cannot be empty.")

    log.info("chat_stream_request", session_id=request.session_id, question=question[:120])
    return EventSourceResponse(_stream_events(question, request.session_id))
