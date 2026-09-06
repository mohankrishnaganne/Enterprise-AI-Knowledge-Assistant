"""Shared Streamlit rendering.

Two entrypoints present the same interface:

- ``ui/app.py`` talks to the FastAPI backend over HTTP (local development, Docker).
- ``streamlit_app.py`` runs the agent in-process (Streamlit Community Cloud, which
  hosts a single process and cannot run a second service alongside it).

The presentation lives here so the two cannot drift. Both consume the same result shape --
the dict ``src.agent.graph.answer_question`` returns, which is exactly what ``POST /chat``
serialises -- so neither entrypoint needs to know which produced it.

Visual styling lives in :mod:`ui.theme`.
"""

from __future__ import annotations

import html

import streamlit as st

from ui.theme import CATEGORY_HEX, GITHUB_URL, render_footer, render_hero, render_metrics

__all__ = [
    "HOW_IT_WORKS",
    "PAGE_INTRO",
    "SAMPLE_QUESTIONS",
    "render_answer",
    "render_empty_state",
    "render_footer",
    "render_hero",
    "render_metrics",
    "render_sidebar_samples",
    "render_status",
]

# Sample questions, each chosen to take a visibly different path through the agent so a
# visitor can see the behaviour rather than read about it.
SAMPLE_QUESTIONS = [
    (
        "📊 Rate limits",
        "How many API requests per minute does the Growth plan allow?",
        "Straight retrieval with a citation",
    ),
    (
        "🔗 Multi-hop",
        "Which two Enterprise renewals are at risk, and which roadmap item addresses it?",
        "Decomposed across two documents, one a PDF",
    ),
    (
        "📋 Policy",
        "What happens if my booked holiday overlaps with an on-call rotation?",
        "Multi-hop over operational policy",
    ),
    (
        "🔁 Self-correction",
        "What is ACME's policy on cryptocurrency payments from customers?",
        "Rewrites twice, then declines honestly",
    ),
]

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
4. **Grade** — an LLM judges every passage
5. **Rewrite** — retry if the evidence is weak
6. **Generate** — answer with citations, or decline
"""

CORPUS_SUMMARY = """
**20 documents · 91 indexed chunks**, across three categories:

- 🔵 **technical** — API reference, auth, rate limits, deployment runbook, architecture, DB schema
- 🟢 **operational** — onboarding, incident response, PTO, on-call, security, expenses
- 🟠 **business** — pricing, quarterly review, competitors, roadmap, partners, support SLA

Two are PDFs, so the PDF ingestion path is genuinely exercised.
"""


# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------
def render_empty_state(pending_key: str = "pending") -> None:
    """Render the first-view prompt: what to ask, and why each example is interesting.

    A blank chat box gives a visitor nothing to react to. These four buttons each
    demonstrate a different branch of the graph, which is the point of the project.
    """
    st.markdown(
        """
<div class="empty-card">
  <h3>Try one of these</h3>
  <p>Each takes a different path through the agent. Open <em>Agent reasoning</em> under any
  answer to see the exact route it took, step by step, with timings.</p>
</div>
""",
        unsafe_allow_html=True,
    )

    for row in (SAMPLE_QUESTIONS[:2], SAMPLE_QUESTIONS[2:]):
        columns = st.columns(len(row))
        for column, (label, question, blurb) in zip(columns, row, strict=True):
            with column:
                if st.button(
                    f"{label}\n\n{blurb}",
                    key=f"empty-{label}",
                    use_container_width=True,
                ):
                    st.session_state[pending_key] = question
                    st.rerun()


# ---------------------------------------------------------------------------
# Citations
# ---------------------------------------------------------------------------
def render_citations(citations: list[dict]) -> None:
    """Render source cards beneath an answer, colour-coded by knowledge-base area."""
    if not citations:
        return

    st.markdown(
        f'<div class="section-title">Sources · {len(citations)}</div>',
        unsafe_allow_html=True,
    )

    for citation in citations:
        source = citation["source"]
        section = citation.get("section") or ""
        category = citation.get("category", "")
        colour = CATEGORY_HEX.get(category, "#6B7280")

        title = source.split("/")[-1]
        if section:
            title += f" › {section}"

        with st.expander(f"[{citation['n']}]  {title}", expanded=False):
            st.markdown(
                f'<span class="cite-badge" style="background:{colour}">{category or "source"}</span>'
                f'<span class="cite-score">similarity {citation["score"]:.3f} · '
                f"<code>{html.escape(citation['chunk_id'])}</code></span>",
                unsafe_allow_html=True,
            )
            st.markdown(f"> {citation['snippet'].strip()}…")
            st.caption(f"`{source}`")


# ---------------------------------------------------------------------------
# Agent trace
# ---------------------------------------------------------------------------
def render_trace(result: dict) -> None:
    """Render the agent's execution path as a timeline.

    Expanded by default when the agent self-corrected, because that is exactly when a
    visitor wants to know why the answer took ten seconds -- or why there is no answer.
    """
    trace = result.get("trace", [])
    if not trace:
        return

    rewrites = result.get("rewrites", 0)
    label = f"🧠 Agent reasoning — {len(trace)} steps"
    if rewrites:
        label += f" · {rewrites} self-correction{'s' if rewrites != 1 else ''}"

    with st.expander(label, expanded=bool(rewrites)):
        if rewrites:
            st.warning(
                f"Retrieval came back irrelevant, so the agent rewrote its search query "
                f"{rewrites} time{'s' if rewrites != 1 else ''} and searched again. "
                "**A linear RAG pipeline would have answered from those first, "
                "irrelevant results.**"
            )

        rows = []
        for step in trace:
            node = step["node"]
            modifier = ""
            if node == "rewrite_query":
                modifier = " is-rewrite"
            elif node == "fallback":
                modifier = " is-fallback"

            rows.append(
                f'<div class="trace-row{modifier}">'
                f"<div>{NODE_ICONS.get(node, '•')}</div>"
                f'<div><span class="trace-node">{html.escape(node)}</span>'
                f'<br><span class="trace-detail">{html.escape(step["detail"])}</span></div>'
                f'<div class="trace-ms">{step["elapsed_ms"]} ms</div>'
                "</div>"
            )
        st.markdown("".join(rows), unsafe_allow_html=True)

        # Rendered as markup rather than st.metric: st.metric truncates its value to the
        # column width, which turned "knowledge" into "knowl..." and "technical" into
        # "techni...". These values are short and must stay readable.
        summary = [
            ("Intent", result.get("intent", "—")),
            ("Category filter", result.get("category_filter") or "none"),
            ("Rewrites", str(rewrites)),
            ("Total time", f"{result.get('latency_ms', 0) / 1000:.1f}s"),
        ]
        cells = "".join(
            f'<div><div class="meta-label">{html.escape(label)}</div>'
            f'<div class="meta-value">{html.escape(value)}</div></div>'
            for label, value in summary
        )
        st.markdown(f'<div class="trace-meta">{cells}</div>', unsafe_allow_html=True)


def render_answer(result: dict) -> None:
    """Render one assistant turn: the answer, its sources, and how it was reached."""
    if result.get("insufficient_evidence"):
        st.warning(result["answer"])
    else:
        st.markdown(result["answer"])

    render_citations(result.get("citations", []))
    render_trace(result)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
def render_status(ready: bool, components: list[dict]) -> None:
    """Render dependency health as compact status rows."""
    if ready:
        st.success("All systems ready")
    else:
        st.error("Some dependencies are unavailable")

    rows = []
    for component in components:
        state = "status-ok" if component["ready"] else "status-bad"
        rows.append(
            f'<div class="status-row"><div class="status-dot {state}"></div>'
            f'<div><span class="status-name">{html.escape(component["name"])}</span><br>'
            f'<span class="status-detail">{html.escape(component.get("detail", ""))}</span>'
            "</div></div>"
        )
    st.markdown("".join(rows), unsafe_allow_html=True)


def render_sidebar_samples(pending_key: str = "pending") -> None:
    """Render compact sample-question buttons in the sidebar."""
    st.markdown("**Try a question**")
    for label, question, _ in SAMPLE_QUESTIONS:
        if st.button(label, use_container_width=True, key=f"sample-{label}"):
            st.session_state[pending_key] = question
            st.rerun()


def render_sidebar_reference() -> None:
    """Render the explanatory sections shared by both entrypoints."""
    with st.expander("How it works", expanded=False):
        st.markdown(HOW_IT_WORKS)

    with st.expander("What's in the knowledge base", expanded=False):
        st.markdown(CORPUS_SUMMARY)

    with st.expander("Why the answers are trustworthy", expanded=False):
        st.markdown(
            "Every retrieved passage is graded by an LLM before it reaches the answer, "
            "and anything judged irrelevant is discarded. That step is what cuts "
            "irrelevant context by **90%** against a naive baseline.\n\n"
            "When nothing relevant survives, the agent rewrites its query and searches "
            "again — up to twice — and then **declines** rather than guessing. "
            "Measured RAGAS faithfulness is **0.95**.\n\n"
            f"[Full methodology →]({GITHUB_URL}/blob/main/reports/retrieval_benchmark.md)"
        )

    st.markdown(
        f'<div style="font-size:.78rem;opacity:.7;margin-top:.6rem">'
        f'<a href="{GITHUB_URL}" style="color:#4F46E5;font-weight:600;text-decoration:none">'
        "★ View the source on GitHub</a></div>",
        unsafe_allow_html=True,
    )
