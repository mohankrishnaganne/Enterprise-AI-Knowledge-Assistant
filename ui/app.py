"""Streamlit chat client.

A thin client over the FastAPI backend. It imports nothing from ``src``, which is what
proves the API is genuinely self-contained rather than sharing process state with the
agent. (``streamlit_app.py`` is the opposite: it runs the agent in-process, because
Streamlit Community Cloud hosts a single process.)

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

# Presentation is shared with streamlit_app.py (the in-process Cloud entrypoint) so the
# two interfaces cannot drift apart.
from ui.components import (  # noqa: E402
    HOW_IT_WORKS,
    NODE_ICONS,
    PAGE_INTRO,
    render_answer,
    render_sidebar_samples,
)

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
    render_sidebar_samples()

    st.divider()
    st.subheader("How it works")
    st.markdown(HOW_IT_WORKS)

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
st.caption(PAGE_INTRO)

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
