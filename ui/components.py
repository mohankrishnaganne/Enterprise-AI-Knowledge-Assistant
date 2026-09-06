"""Shared Streamlit rendering.

Two entrypoints present the same interface:

- ``ui/app.py`` talks to the FastAPI backend over HTTP (local development, Docker).
- ``streamlit_app.py`` runs the agent in-process (Streamlit Community Cloud, which
  hosts a single process and cannot run a second service alongside it).

The presentation lives here so the two cannot drift. Both consume the same result
shape -- the dict ``src.agent.graph.answer_question`` returns, which is also exactly
what ``POST /chat`` serialises -- so neither entrypoint needs to know which produced it.
"""

from __future__ import annotations

import streamlit as st

# Questions that each demonstrate a different path through the agent.
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

PAGE_INTRO = (
    "Ask about ACME's technical documentation, operational policies, or business "
    "information. Answers are grounded in retrieved passages and cited; when the "
    "documentation does not cover something, the assistant says so instead of guessing."
)

HOW_IT_WORKS = """
1. **Route** — classify intent, pick a category filter
2. **Decompose** — split compound questions
3. **Retrieve** — filtered search + MMR
4. **Grade** — LLM judges every passage
5. **Rewrite** — retry if the evidence is weak
6. **Generate** — answer with citations, or decline
"""


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

    Expanded by default when the agent self-corrected, because that is exactly when a
    user wants to know why the answer took thirty seconds -- or why there is no answer.
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
    """Render one assistant turn: the answer, its sources, and how it was reached."""
    if result.get("insufficient_evidence"):
        st.warning(result["answer"])
    else:
        st.markdown(result["answer"])

    render_citations(result.get("citations", []))
    render_trace(result)


def render_sidebar_samples(on_click_key: str = "pending") -> None:
    """Render the sample-question buttons, storing the choice in session state."""
    st.subheader("Try a question")
    st.caption("Each takes a different path through the agent.")
    for label, question in SAMPLE_QUESTIONS:
        if st.button(label, use_container_width=True, key=f"sample-{label}"):
            st.session_state[on_click_key] = question
            st.rerun()
