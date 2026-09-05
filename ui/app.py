"""Streamlit chat client.

A thin client over the FastAPI backend -- it imports nothing from ``src``, so it proves
the API is genuinely self-contained rather than sharing process state with the agent.

The interface has three parts:

1. The chat transcript.
2. **Citation cards** under each answer, showing which passage supports it and how
   strongly it matched.
3. The **agent reasoning panel**, which renders the execution path. This is the part
   worth showing someone: on a question the corpus cannot answer, you watch it retrieve,
   reject the evidence, rewrite the query, try again, and then decline.

Run with ``streamlit run ui/app.py`` while the API is up on :8000.
"""

from __future__ import annotations

import json
import os
import uuid

import requests
import streamlit as st

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
REQUEST_TIMEOUT = 120

# Questions that demonstrate a different path through the graph each.
SAMPLE_QUESTIONS = [
    ("Rate limits", "How many API requests per minute does the Growth plan allow?"),
    (
        "Multi-hop",
        "Which two Enterprise renewals are at risk, and which roadmap item addresses it?",
    ),
    ("Policy", "What happens if my booked holiday overlaps with an on-call rotation?"),
    ("Self-correction", "What is ACME's policy on cryptocurrency payments from customers?"),
]

# Icons for the trace panel. The rewrite and fallback nodes are the interesting ones.
NODE_ICONS = {
    "route_query": "🧭",
    "decompose_query": "🔀",
    "retrieve": "🔍",
    "grade_documents": "⚖️",
    "validate_sources": "✅",
    "generate": "✍️",
    "rewrite_query": "🔁",
    "direct_answer": "💬",
    "fallback": "🚫",
}

CATEGORY_COLORS = {"technical": "blue", "operational": "green", "business": "orange"}


st.set_page_config(
    page_title="ACME Knowledge Assistant",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)


def api_ready() -> tuple[bool, list[dict]]:
    """Ask the backend whether it can serve requests."""
    try:
        response = requests.get(f"{API_BASE_URL}/ready", timeout=20)
        response.raise_for_status()
        payload = response.json()
        return payload["ready"], payload["components"]
    except Exception as exc:  # noqa: BLE001
        return False, [{"name": "api", "ready": False, "detail": str(exc)[:200]}]


def ask(question: str, session_id: str) -> dict:
    """Send a question to the backend and return the parsed response."""
    response = requests.post(
        f"{API_BASE_URL}/chat",
        json={"question": question, "session_id": session_id},
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code >= 400:
        detail = response.json().get("detail", response.text)
        raise RuntimeError(detail)
    return response.json()


def ask_streaming(question: str, session_id: str, placeholder) -> dict:
    """Stream progress into ``placeholder``, returning the final payload.

    Falls back to the non-streaming endpoint if the stream fails, so a proxy that
    buffers SSE degrades to a slower experience rather than a broken one.
    """
    steps: list[str] = []
    try:
        with requests.post(
            f"{API_BASE_URL}/chat/stream",
            json={"question": question, "session_id": session_id},
            stream=True,
            timeout=REQUEST_TIMEOUT,
            headers={"Accept": "text/event-stream"},
        ) as response:
            response.raise_for_status()
            event_name = ""

            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                if raw_line.startswith("event:"):
                    event_name = raw_line.split(":", 1)[1].strip()
                    continue
                if not raw_line.startswith("data:"):
                    continue

                payload = json.loads(raw_line.split(":", 1)[1].strip())

                if event_name == "node":
                    icon = NODE_ICONS.get(payload["node"], "•")
                    steps.append(f"{icon} **{payload['node']}** — {payload['detail']}")
                    placeholder.markdown("\n\n".join(steps))
                elif event_name == "error":
                    raise RuntimeError(payload.get("detail", "stream failed"))
                elif event_name == "done":
                    return payload
    except Exception:  # noqa: BLE001
        placeholder.markdown("_Streaming unavailable; waiting for the full response…_")
        return ask(question, session_id)

    raise RuntimeError("The stream ended before returning an answer.")


def render_citations(citations: list[dict]) -> None:
    """Render source cards beneath an answer."""
    if not citations:
        return

    st.caption(f"{len(citations)} source{'s' if len(citations) != 1 else ''}")
    for citation in citations:
        header = f"**[{citation['n']}]** {citation['source']}"
        if citation.get("section"):
            header += f" › {citation['section']}"

        with st.expander(f"{header}  ·  match {citation['score']:.3f}", expanded=False):
            category = citation.get("category", "")
            if category:
                st.markdown(
                    f":{CATEGORY_COLORS.get(category, 'gray')}[**{category}**] · "
                    f"`{citation['chunk_id']}`"
                )
            st.markdown(f"> {citation['snippet'].strip()}…")


def render_trace(result: dict) -> None:
    """Render the agent's execution path.

    Expanded by default when the agent had to self-correct, because that is exactly the
    case where a user wants to know why the answer took thirty seconds -- or why there
    is no answer at all.
    """
    trace = result.get("trace", [])
    if not trace:
        return

    rewrites = result.get("rewrites", 0)
    label = f"🧠 Agent reasoning — {len(trace)} steps"
    if rewrites:
        label += f", {rewrites} self-correction{'s' if rewrites != 1 else ''}"

    with st.expander(label, expanded=bool(rewrites)):
        if rewrites:
            st.info(
                f"Retrieval came back irrelevant, so the agent rewrote its search query "
                f"{rewrites} time{'s' if rewrites != 1 else ''} and searched again. "
                "A linear RAG pipeline would have answered from the first, irrelevant results."
            )

        for step in trace:
            icon = NODE_ICONS.get(step["node"], "•")
            columns = st.columns([0.28, 0.58, 0.14])
            columns[0].markdown(f"{icon} **{step['node']}**")
            columns[1].markdown(step["detail"])
            columns[2].markdown(f"`{step['elapsed_ms']} ms`")

        st.divider()
        meta = st.columns(4)
        meta[0].metric("Intent", result.get("intent", "—"))
        meta[1].metric("Filter", result.get("category_filter") or "none")
        meta[2].metric("Rewrites", rewrites)
        meta[3].metric("Latency", f"{result.get('latency_ms', 0) / 1000:.1f}s")


def render_answer(result: dict) -> None:
    """Render one assistant turn."""
    if result.get("insufficient_evidence"):
        st.warning(result["answer"])
    else:
        st.markdown(result["answer"])

    render_citations(result.get("citations", []))
    render_trace(result)


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "pending" not in st.session_state:
    st.session_state.pending = None


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("📚 ACME Assistant")
    st.caption("Agentic RAG over internal documentation")

    ready, components = api_ready()
    if ready:
        st.success("Backend ready")
    else:
        st.error("Backend not ready")
    for component in components:
        st.markdown(
            f"{'🟢' if component['ready'] else '🔴'} **{component['name']}** — "
            f"{component.get('detail', '')}"
        )

    st.divider()
    st.subheader("Try a question")
    st.caption("Each takes a different path through the agent.")
    for label, question in SAMPLE_QUESTIONS:
        if st.button(label, use_container_width=True, key=f"sample-{label}"):
            st.session_state.pending = question
            st.rerun()

    st.divider()
    st.subheader("How it works")
    st.markdown(
        """
1. **Route** — classify intent, pick a category filter
2. **Decompose** — split compound questions
3. **Retrieve** — filtered search + MMR
4. **Grade** — LLM judges every passage
5. **Rewrite** — retry if the evidence is weak
6. **Generate** — answer with citations, or decline
"""
    )

    st.divider()
    if st.button("Clear conversation", use_container_width=True):
        st.session_state.messages = []
        st.session_state.session_id = str(uuid.uuid4())
        st.rerun()
    st.caption(f"API: `{API_BASE_URL}`")


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------
st.title("Enterprise AI Knowledge Assistant")
st.caption(
    "Ask about ACME's technical documentation, operational policies, or business "
    "information. Answers are grounded in retrieved passages and cited; when the "
    "documentation does not cover something, the assistant says so instead of guessing."
)

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message["role"] == "user":
            st.markdown(message["content"])
        else:
            render_answer(message["result"])

question = st.chat_input("Ask about ACME's documentation…") or st.session_state.pending
st.session_state.pending = None

if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        progress = st.empty()
        try:
            with st.spinner("Thinking…"):
                result = ask_streaming(question, st.session_state.session_id, progress)
            progress.empty()
            render_answer(result)
            st.session_state.messages.append({"role": "assistant", "result": result})
        except Exception as exc:  # noqa: BLE001
            progress.empty()
            st.error(f"Request failed: {exc}")
            st.caption(f"Is the backend running at {API_BASE_URL}?  Start it with `make api`.")
