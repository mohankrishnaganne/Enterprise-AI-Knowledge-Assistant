"""FastAPI application.

The lifespan handler does the expensive work once, at startup, rather than on the first
unlucky request:

- **Loads the embedding model.** Roughly 20 seconds cold on CPU. Without warming it here
  the first user question takes ~25 seconds and looks broken, while every later one takes
  two. This was measured, not assumed.
- **Compiles the LangGraph workflow.** Cached thereafter.
- **Verifies the Groq model ids.** Groq retires models periodically; logging a clear
  warning at boot beats discovering it as a 404 inside a node.

Startup deliberately does not abort when a dependency is unavailable. A container that
refuses to start is harder to diagnose than one that starts and reports the problem on
``/ready``.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import chat, health
from src.config import settings
from src.logging_conf import configure_logging, get_logger

log = get_logger(__name__)

DESCRIPTION = """
Agentic RAG over ACME Corp's internal documentation.

A LangGraph workflow routes each question, decomposes it when compound, retrieves with
metadata filtering and MMR, grades every retrieved passage with an LLM judge, and
**rewrites the query and retries** when the evidence is weak -- declining to answer
rather than guessing when it still finds nothing.

Every response carries the agent's execution path in `trace`, so the retry loop is
visible rather than implied.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Warm expensive resources at startup and log a readiness summary."""
    configure_logging()
    started = time.perf_counter()
    log.info("api_starting", index=settings.pinecone_index_name)

    # --- Embedding model ------------------------------------------------------
    try:
        from src.retrieval.embedder import get_embedder

        embed_started = time.perf_counter()
        get_embedder()
        log.info(
            "embedder_warmed",
            model=settings.embedding_model,
            seconds=round(time.perf_counter() - embed_started, 1),
        )
    except Exception as exc:  # noqa: BLE001
        log.error("embedder_warmup_failed", error=str(exc))

    # --- Graph ----------------------------------------------------------------
    try:
        from src.agent.graph import compile_graph

        compile_graph()
    except Exception as exc:  # noqa: BLE001
        log.error("graph_compile_failed", error=str(exc))

    # --- Model availability ---------------------------------------------------
    try:
        from src.agent.llm import check_models_available

        for problem in check_models_available():
            log.warning("groq_model_unavailable", problem=problem)
    except Exception as exc:  # noqa: BLE001
        log.warning("groq_check_failed", error=str(exc))

    log.info("api_ready", startup_seconds=round(time.perf_counter() - started, 1))
    yield
    log.info("api_shutdown")


app = FastAPI(
    title="Enterprise AI Knowledge Assistant",
    description=DESCRIPTION,
    version=health.VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# The Streamlit UI is served from a different origin (8501 locally, and a different
# process on Hugging Face Spaces), so it needs CORS. Kept permissive because this API
# holds no user data and performs no authenticated writes; tighten `allow_origins` if
# that ever changes.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(chat.router)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log method, path, status and duration for every request."""
    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = int((time.perf_counter() - started) * 1000)

    # Health probes fire constantly; logging them buries the interesting lines.
    if request.url.path not in ("/health", "/ready"):
        log.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
        )
    response.headers["X-Response-Time-Ms"] = str(duration_ms)
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a structured error instead of an HTML traceback page."""
    log.error("unhandled_exception", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "detail": "An unexpected error occurred."},
    )


@app.get("/", include_in_schema=False)
def root() -> dict:
    """Point a browser hitting the root at the interactive docs."""
    return {
        "name": "Enterprise AI Knowledge Assistant",
        "version": health.VERSION,
        "docs": "/docs",
        "endpoints": ["POST /chat", "POST /chat/stream", "GET /health", "GET /ready"],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api.main:app", host=settings.api_host, port=settings.api_port, reload=False)
