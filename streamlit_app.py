"""Streamlit Community Cloud entrypoint — runs the agent in-process.

Streamlit Cloud hosts a single process, so there is no FastAPI service to call. This
entrypoint imports the LangGraph agent directly and invokes it. ``ui/app.py`` remains the
HTTP client used locally and in Docker, and both share their presentation via
``ui/components.py`` so the two cannot drift apart.

Two things here are load-order sensitive and easy to get wrong:

1. **Secrets are injected into the environment before anything from ``src`` is
   imported.** ``src.config`` builds its settings singleton at import time, so importing
   it first would freeze in the placeholder values and every request would fail with a
   missing-credentials error that looks nothing like a configuration problem.
2. **The compiled graph is cached with ``st.cache_resource``.** Streamlit re-executes
   this script top-to-bottom on every interaction, so without the cache the warm-up
   would repeat on every click.

Embeddings here come from the HuggingFace Inference API rather than a local model.
Streamlit Cloud runs Python 3.14, for which torch 2.5.x publishes no wheels at all, and
the CUDA build it would otherwise resolve is far larger than the free tier allows. The
hosted endpoint serves the same ``BAAI/bge-small-en-v1.5`` and returns identical vectors
(verified at cosine 1.000000), so this deployment queries the very same Pinecone index
and the committed benchmark numbers describe it accurately.

Deployed from https://share.streamlit.io pointing at this file.
"""

from __future__ import annotations

import os

import streamlit as st

# Must precede any Streamlit output.
st.set_page_config(
    page_title="ACME Knowledge Assistant",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

REQUIRED_SECRETS = ("GROQ_API_KEY", "PINECONE_API_KEY", "HF_TOKEN")

# Non-secret defaults. Streamlit Cloud has no .env file, and these must match the values
# the retrieval benchmark measured, or the deployed app is not the system that was
# evaluated.
CONFIG_DEFAULTS = {
    "GROQ_MODEL_STRONG": "openai/gpt-oss-120b",
    "GROQ_MODEL_FAST": "openai/gpt-oss-20b",
    "PINECONE_INDEX_NAME": "enterprise-knowledge",
    "PINECONE_NAMESPACE": "v1",
    "EMBEDDING_MODEL": "BAAI/bge-small-en-v1.5",
    "EMBEDDING_DIM": "384",
    # Hosted embeddings, not local. Streamlit Cloud runs Python 3.14, where torch has
    # no wheels for the pinned version and the CUDA build would far exceed the free
    # tier anyway. The Inference API serves the same model and returns identical
    # vectors (cosine 1.000000), so the Pinecone index built locally is queried
    # unchanged and the benchmark numbers still describe this deployment.
    "EMBEDDING_BACKEND": "hf_api",
    "RETRIEVAL_TOP_K": "5",
    "RETRIEVAL_FETCH_K": "20",
    "RETRIEVAL_MMR_LAMBDA": "1.0",
    "RETRIEVAL_SCORE_THRESHOLD": "0.62",
    "MAX_QUERY_REWRITES": "2",
    "MAX_SUBQUERIES": "3",
    "LOG_LEVEL": "INFO",
}


def bootstrap_environment() -> list[str]:
    """Populate the environment from every available source. Returns what is missing.

    Precedence, highest first: an existing environment variable, then Streamlit secrets
    (how Streamlit Cloud supplies them), then a local ``.env`` (so this entrypoint can be
    run and debugged on a developer machine exactly as Cloud will run it).

    Runs before ``src`` is imported anywhere in this module -- see the note above.
    """
    for key, value in CONFIG_DEFAULTS.items():
        os.environ.setdefault(key, value)

    # Local convenience only. Streamlit Cloud has no .env, so this is a no-op there.
    try:
        from dotenv import load_dotenv

        load_dotenv(override=False)
    except Exception:  # noqa: BLE001 - python-dotenv absent or no file; not an error
        pass

    missing: list[str] = []
    for key in REQUIRED_SECRETS:
        value = None
        try:
            value = st.secrets.get(key)
        except Exception:  # noqa: BLE001 - no secrets file configured at all
            value = None
        value = value or os.environ.get(key)

        if value:
            os.environ[key] = str(value)
        else:
            missing.append(key)
    return missing


missing_secrets = bootstrap_environment()

if missing_secrets:
    st.title("Enterprise AI Knowledge Assistant")
    st.error("Missing required secret(s): " + ", ".join(f"`{k}`" for k in missing_secrets))
    st.markdown(
        """
This app needs two free API keys. Add them in **Manage app → Settings → Secrets**
as TOML:

```toml
GROQ_API_KEY = "gsk_..."
PINECONE_API_KEY = "pcsk_..."
HF_TOKEN = "hf_..."
```

- Groq key: <https://console.groq.com/keys>
- Pinecone key: <https://app.pinecone.io>
- HuggingFace token: <https://huggingface.co/settings/tokens> — must be a
  fine-grained token with **Make calls to Inference Providers** enabled. A plain
  read token returns 403.

The Pinecone index must already be populated — this app queries an existing index
rather than ingesting on startup. Run `python scripts/run_ingestion.py` locally first.
"""
    )
    st.stop()


# Safe to import now that the environment is populated.
from ui.components import (  # noqa: E402
    HOW_IT_WORKS,
    PAGE_INTRO,
    render_answer,
    render_sidebar_samples,
)


@st.cache_resource(show_spinner="Warming up the agent…")
def load_agent():
    """Compile the graph and warm the embedding backend once per process.

    ``st.cache_resource`` is essential rather than an optimisation: Streamlit re-runs
    this script top-to-bottom on every interaction, so without it the warm-up would
    repeat on every click.
    """
    from src.agent.graph import answer_question, compile_graph
    from src.retrieval.embedder import warm_up

    warm_up()
    compile_graph()
    return answer_question


@st.cache_data(ttl=300, show_spinner=False)
def check_backend() -> tuple[bool, list[dict]]:
    """Report dependency health, cached briefly so it does not run on every rerun."""
    components: list[dict] = []

    try:
        from src.config import settings
        from src.retrieval.embedder import warm_up

        warm_up()
        backend = (
            "HuggingFace Inference API" if settings.embedding_backend == "hf_api" else "local model"
        )
        components.append(
            {
                "name": "embeddings",
                "ready": True,
                "detail": f"{backend} ({settings.embedding_model})",
            }
        )
    except Exception as exc:  # noqa: BLE001
        components.append({"name": "embeddings", "ready": False, "detail": str(exc)[:150]})

    try:
        from src.config import settings
        from src.retrieval.vector_store import describe_stats

        stats = describe_stats()
        vectors = stats["namespaces"].get(settings.pinecone_namespace, 0)
        components.append(
            {
                "name": "pinecone",
                "ready": vectors > 0,
                "detail": f"{vectors} vectors in '{settings.pinecone_namespace}'"
                if vectors
                else "namespace is empty; run scripts/run_ingestion.py",
            }
        )
    except Exception as exc:  # noqa: BLE001
        components.append({"name": "pinecone", "ready": False, "detail": str(exc)[:150]})

    try:
        from src.agent.llm import check_models_available

        problems = check_models_available()
        components.append(
            {
                "name": "groq",
                "ready": not problems,
                "detail": problems[0][:150] if problems else "configured models available",
            }
        )
    except Exception as exc:  # noqa: BLE001
        components.append({"name": "groq", "ready": False, "detail": str(exc)[:150]})

    return all(c["ready"] for c in components), components


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending" not in st.session_state:
    st.session_state.pending = None


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("📚 ACME Assistant")
    st.caption("Agentic RAG over internal documentation")

    ready, components = check_backend()
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
        st.rerun()
    st.caption("Agent runs in-process; embeddings are served by the HuggingFace Inference API.")


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
        try:
            answer_question = load_agent()
            with st.spinner("Thinking… (self-correcting questions take longer)"):
                result = answer_question(question)
            render_answer(result)
            st.session_state.messages.append({"role": "assistant", "result": result})
        except Exception as exc:  # noqa: BLE001
            st.error(f"The agent could not complete this request: {exc}")
