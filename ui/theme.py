"""Visual theme: CSS, colour tokens and the chrome around the chat.

Streamlit's defaults are serviceable but anonymous, and this app's first job is to be
looked at by someone deciding whether to read the code. So the shell -- hero, metrics,
empty state, footer -- is hand-built, while the chat itself stays native Streamlit so it
keeps working across version upgrades.

Selectors use ``data-testid`` attributes rather than generated class names, because the
generated ones churn between Streamlit releases and would silently stop applying.
"""

from __future__ import annotations

import streamlit as st

# Palette. Indigo primary against near-neutral greys; the category colours double as the
# accent for citation cards so a source's area is identifiable at a glance.
PRIMARY = "#4F46E5"
CATEGORY_HEX = {
    "technical": "#2563EB",
    "operational": "#059669",
    "business": "#D97706",
}

# Headline numbers, sourced from the committed reports. Kept here rather than recomputed
# so the UI cannot quietly disagree with reports/retrieval_benchmark.md.
HEADLINE_METRICS = [
    ("90%", "fewer irrelevant results", "vs. a naive RAG baseline, on a held-out split"),
    ("0.95", "RAGAS faithfulness", "share of answer claims traceable to a source"),
    ("100%", "answer coverage kept", "no question lost while cutting the noise"),
    ("~4s", "typical response", "self-correcting questions take longer"),
]

GITHUB_URL = "https://github.com/mohankrishnaganne/Enterprise-AI-Knowledge-Assistant"

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"], [data-testid="stAppViewContainer"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

/* Roomier main column; Streamlit's default top padding wastes the first screenful. */
[data-testid="stAppViewContainer"] > .main .block-container {
    padding-top: 2.2rem;
    padding-bottom: 6rem;
    max-width: 1080px;
}

/* Streamlit's own header bar is chrome we do not need. */
[data-testid="stHeader"] { background: transparent; }

/* ---------------- Hero ---------------- */
.hero {
    background: linear-gradient(135deg, #4F46E5 0%, #7C3AED 55%, #9333EA 100%);
    border-radius: 18px;
    padding: 2.1rem 2.3rem 1.9rem;
    color: #fff;
    margin-bottom: 1.1rem;
    box-shadow: 0 12px 32px -12px rgba(79, 70, 229, .55);
}
.hero h1 {
    font-size: 2.05rem; font-weight: 800; letter-spacing: -.025em;
    margin: 0 0 .5rem; color: #fff; line-height: 1.15;
}
.hero p { font-size: 1.02rem; line-height: 1.6; margin: 0; color: rgba(255,255,255,.93); max-width: 60ch; }
.hero .eyebrow {
    display: inline-block; font-size: .7rem; font-weight: 700; letter-spacing: .1em;
    text-transform: uppercase; background: rgba(255,255,255,.18);
    padding: .3rem .7rem; border-radius: 99px; margin-bottom: .9rem;
    border: 1px solid rgba(255,255,255,.25);
}
.hero-tags { margin-top: 1.1rem; display: flex; flex-wrap: wrap; gap: .45rem; }
.hero-tags span {
    font-size: .74rem; font-weight: 600; background: rgba(255,255,255,.15);
    border: 1px solid rgba(255,255,255,.22); padding: .28rem .65rem; border-radius: 7px;
}

/* ---------------- Metric strip ---------------- */
.metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: .8rem; margin: 0 0 1.6rem; }
.metric {
    background: rgba(127,127,127,.06); border: 1px solid rgba(127,127,127,.16);
    border-radius: 13px; padding: .95rem 1.05rem;
}
.metric .value { font-size: 1.55rem; font-weight: 800; color: #4F46E5; letter-spacing: -.02em; line-height: 1.1; }
.metric .label { font-size: .82rem; font-weight: 650; margin-top: .15rem; }
.metric .hint { font-size: .715rem; opacity: .65; margin-top: .3rem; line-height: 1.35; }
@media (max-width: 900px) { .metrics { grid-template-columns: repeat(2, 1fr); } }

/* ---------------- Section heading ---------------- */
.section-title {
    font-size: .74rem; font-weight: 750; letter-spacing: .11em; text-transform: uppercase;
    opacity: .55; margin: 1.9rem 0 .7rem;
}

/* ---------------- Empty state ---------------- */
.empty-card {
    border: 1px dashed rgba(127,127,127,.32); border-radius: 14px;
    padding: 1.5rem 1.6rem; margin-bottom: 1rem; background: rgba(127,127,127,.03);
}
.empty-card h3 { margin: 0 0 .4rem; font-size: 1.02rem; font-weight: 700; }
.empty-card p { margin: 0; font-size: .88rem; opacity: .75; line-height: 1.55; }

/* Sample-question buttons: quiet until hovered. */
[data-testid="stMainBlockContainer"] .stButton > button {
    border-radius: 11px; border: 1px solid rgba(127,127,127,.25);
    padding: .72rem .9rem; font-weight: 600; font-size: .85rem;
    text-align: left; line-height: 1.35; height: 100%; width: 100%;
    transition: border-color .13s ease, transform .13s ease, box-shadow .13s ease;
}
[data-testid="stMainBlockContainer"] .stButton > button:hover {
    border-color: #4F46E5; color: #4F46E5; transform: translateY(-2px);
    box-shadow: 0 7px 18px -9px rgba(79,70,229,.6);
}

/* ---------------- Trace timeline ---------------- */
.trace-row {
    display: grid; grid-template-columns: 30px 1fr auto; gap: .7rem;
    align-items: baseline; padding: .42rem 0;
    border-bottom: 1px solid rgba(127,127,127,.11);
}
.trace-row:last-child { border-bottom: none; }
.trace-node { font-weight: 700; font-size: .845rem; }
.trace-detail { font-size: .845rem; opacity: .8; }
.trace-ms {
    font-size: .715rem; opacity: .55; font-variant-numeric: tabular-nums;
    white-space: nowrap; font-weight: 600;
}
.trace-row.is-rewrite .trace-node,
.trace-row.is-rewrite .trace-detail { color: #D97706; }
.trace-row.is-fallback .trace-node,
.trace-row.is-fallback .trace-detail { color: #DC2626; }

.trace-meta {
    display: grid; grid-template-columns: repeat(4, 1fr); gap: .8rem;
    margin-top: .95rem; padding-top: .85rem;
    border-top: 1px solid rgba(127,127,127,.16);
}
.meta-label {
    font-size: .68rem; font-weight: 700; letter-spacing: .07em;
    text-transform: uppercase; opacity: .52;
}
.meta-value { font-size: .96rem; font-weight: 700; margin-top: .15rem; }
@media (max-width: 720px) { .trace-meta { grid-template-columns: repeat(2, 1fr); } }

/* ---------------- Citations ---------------- */
.cite-badge {
    display: inline-block; font-size: .68rem; font-weight: 750; letter-spacing: .05em;
    text-transform: uppercase; padding: .16rem .5rem; border-radius: 5px;
    color: #fff; margin-right: .4rem;
}
.cite-score {
    font-size: .715rem; opacity: .6; font-variant-numeric: tabular-nums; font-weight: 600;
}
blockquote {
    border-left: 3px solid rgba(79,70,229,.35) !important;
    padding-left: .9rem !important; font-size: .875rem; opacity: .87;
}

/* ---------------- Sidebar ---------------- */
[data-testid="stSidebar"] { border-right: 1px solid rgba(127,127,127,.14); }
[data-testid="stSidebar"] .stButton > button {
    border-radius: 9px; font-size: .82rem; font-weight: 600;
}
.status-row {
    display: flex; align-items: flex-start; gap: .45rem;
    font-size: .79rem; padding: .26rem 0; line-height: 1.4;
}
.status-dot { width: 8px; height: 8px; border-radius: 50%; margin-top: .38rem; flex: 0 0 8px; }
.status-ok { background: #10B981; }
.status-bad { background: #EF4444; }
.status-name { font-weight: 700; }
.status-detail { opacity: .62; }

/* ---------------- Footer ---------------- */
.footer {
    margin-top: 2.6rem; padding-top: 1.1rem;
    border-top: 1px solid rgba(127,127,127,.16);
    font-size: .77rem; opacity: .62; line-height: 1.65;
}
.footer a { color: #4F46E5; text-decoration: none; font-weight: 600; }
.footer a:hover { text-decoration: underline; }
</style>
"""


def inject() -> None:
    """Inject the stylesheet. Call once, immediately after ``set_page_config``."""
    st.markdown(CSS, unsafe_allow_html=True)


def render_hero() -> None:
    """Render the banner that states what this is and what makes it different."""
    st.markdown(
        """
<div class="hero">
  <div class="eyebrow">Agentic RAG · LangGraph</div>
  <h1>Enterprise AI Knowledge Assistant</h1>
  <p>
    Answers questions over a company knowledge base — and when the evidence is weak it
    <strong>rewrites its own search and tries again</strong>, then declines rather than
    guessing. Every claim is grounded in a retrieved passage and cited.
  </p>
  <div class="hero-tags">
    <span>LangGraph</span><span>Pinecone</span><span>Groq · gpt-oss</span>
    <span>BGE embeddings</span><span>FastAPI</span><span>RAGAS-evaluated</span>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def render_metrics() -> None:
    """Render the measured-results strip.

    Placed above the fold on purpose: the numbers are the reason to keep reading, and
    they are the part of this project that most portfolio RAG demos cannot show.
    """
    cards = "".join(
        f'<div class="metric"><div class="value">{value}</div>'
        f'<div class="label">{label}</div><div class="hint">{hint}</div></div>'
        for value, label, hint in HEADLINE_METRICS
    )
    st.markdown(f'<div class="metrics">{cards}</div>', unsafe_allow_html=True)


def render_footer() -> None:
    """Render the footer, including where the numbers above come from."""
    st.markdown(
        f"""
<div class="footer">
  Built as a portfolio project. The corpus is synthetic — a fictional company called ACME
  Corp — so nothing here is confidential.
  <br>
  Metrics come from committed, reproducible scripts:
  <a href="{GITHUB_URL}/blob/main/reports/retrieval_benchmark.md">retrieval benchmark</a> ·
  <a href="{GITHUB_URL}/blob/main/reports/ragas_scores.md">RAGAS scores</a> ·
  <a href="{GITHUB_URL}/blob/main/docs/architecture.md">architecture</a> ·
  <a href="{GITHUB_URL}">source</a>
</div>
""",
        unsafe_allow_html=True,
    )
