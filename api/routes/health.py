"""Liveness and readiness endpoints.

The distinction matters for deployment. ``/health`` answers "is the process alive" and
must stay cheap -- a platform restarts the container when it fails. ``/ready`` answers
"can this process actually serve a request", which means checking Pinecone and Groq, and
is what you look at when the app is up but every answer is failing.
"""

from __future__ import annotations

from fastapi import APIRouter

from api.models import HealthResponse, ReadinessComponent, ReadinessResponse
from src.logging_conf import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["health"])

VERSION = "0.1.0"


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
def health() -> HealthResponse:
    """Return OK if the process is running. Makes no external calls."""
    return HealthResponse(version=VERSION)


@router.get("/ready", response_model=ReadinessResponse, summary="Readiness probe")
def ready() -> ReadinessResponse:
    """Check every dependency required to answer a question.

    Never raises: a readiness probe that 500s tells you less than one that reports which
    component is broken.
    """
    components: list[ReadinessComponent] = []

    # --- Embedding model (local; loaded during startup) -----------------------
    try:
        from src.retrieval.embedder import get_embedder

        get_embedder()
        components.append(ReadinessComponent(name="embeddings", ready=True, detail="model loaded"))
    except Exception as exc:  # noqa: BLE001
        components.append(ReadinessComponent(name="embeddings", ready=False, detail=str(exc)[:200]))

    # --- Pinecone -------------------------------------------------------------
    try:
        from src.config import settings
        from src.retrieval.vector_store import describe_stats

        stats = describe_stats()
        vectors = stats["namespaces"].get(settings.pinecone_namespace, 0)
        components.append(
            ReadinessComponent(
                name="pinecone",
                # An empty namespace means ingestion never ran; the API would answer
                # every question with the fallback, which is worse than reporting it.
                ready=vectors > 0,
                detail=f"{vectors} vectors in namespace '{settings.pinecone_namespace}'"
                if vectors
                else "namespace is empty; run scripts/run_ingestion.py",
            )
        )
    except Exception as exc:  # noqa: BLE001
        components.append(ReadinessComponent(name="pinecone", ready=False, detail=str(exc)[:200]))

    # --- Groq -----------------------------------------------------------------
    try:
        from src.agent.llm import check_models_available

        problems = check_models_available()
        components.append(
            ReadinessComponent(
                name="groq",
                ready=not problems,
                detail=problems[0][:200] if problems else "configured models available",
            )
        )
    except Exception as exc:  # noqa: BLE001
        components.append(ReadinessComponent(name="groq", ready=False, detail=str(exc)[:200]))

    return ReadinessResponse(
        ready=all(component.ready for component in components), components=components
    )
