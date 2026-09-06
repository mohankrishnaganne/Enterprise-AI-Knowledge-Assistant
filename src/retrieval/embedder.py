"""Embeddings, with two interchangeable backends.

Both serve ``BAAI/bge-small-en-v1.5`` and produce **identical** 384-dimensional vectors --
measured at cosine 1.000000 between them -- so the same Pinecone index serves either and
the retrieval benchmark's numbers hold whichever is configured:

``local`` (default)
    sentence-transformers on CPU. No network call, no rate limit, works offline once the
    ~130 MB model is cached. Costs ~2 GB of installed dependencies (torch) and ~40 s of
    startup. Used for ingestion, evaluation, Docker and local development.

``hf_api``
    HuggingFace Inference API. Needs only ``huggingface_hub``, which is what makes the
    app deployable on a free tier that cannot hold torch -- Streamlit Community Cloud
    runs Python 3.14, where torch 2.5.x has no wheels at all, and the CUDA build it would
    otherwise pull is far too large. Trades a network round trip per query for a
    deployable footprint.

Two details that matter for retrieval quality with BGE models, and apply to both backends:

1. **Normalised vectors.** BGE is trained for cosine similarity, and the Pinecone index
   uses ``metric="cosine"``. Normalising at encode time also makes the dot product equal
   cosine, which keeps the MMR maths in ``retriever.py`` straightforward.
2. **An asymmetric query prefix.** BGE was trained with the instruction
   ``"Represent this sentence for searching relevant passages: "`` prepended to *queries*
   but not to passages. Omitting it quietly costs retrieval accuracy, which is why it is
   applied in one place that every caller goes through.
"""

from __future__ import annotations

import math
from functools import lru_cache

from src.config import settings
from src.logging_conf import get_logger

log = get_logger(__name__)

# The instruction prefix BGE v1.5 English models were trained with, applied to queries
# only. See the model card on the HuggingFace hub.
BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


def _query_instruction_for(model_name: str) -> str:
    """Return the query prefix appropriate to the model, or an empty string."""
    return BGE_QUERY_INSTRUCTION if "bge" in model_name.lower() else ""


def _normalise(vector: list[float]) -> list[float]:
    """L2-normalise, so the dot product equals cosine similarity."""
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else vector


def _check_dimension(actual: int) -> None:
    """Fail fast on a dimension mismatch rather than at upsert time.

    A Pinecone index's dimension is immutable, so this otherwise surfaces much later as
    an opaque server-side error.
    """
    if actual != settings.embedding_dim:
        raise RuntimeError(
            f"EMBEDDING_DIM is {settings.embedding_dim} but {settings.embedding_model} "
            f"produces {actual}-dimensional vectors. Update .env and recreate the "
            "Pinecone index -- dimension cannot be changed in place."
        )


# ---------------------------------------------------------------------------
# Local backend (sentence-transformers)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_embedder():
    """Return the process-wide local embedding model.

    Cached because loading sentence-transformers takes tens of seconds and allocates
    hundreds of megabytes; no server may pay that per request.
    """
    # Imported lazily so the hf_api backend never requires torch to be installed.
    from langchain_huggingface import HuggingFaceEmbeddings

    log.info(
        "loading_embedding_model",
        model=settings.embedding_model,
        device=settings.embedding_device,
    )

    # NOTE: langchain-huggingface 1.x dropped the `query_instruction` field that 0.x had,
    # so the BGE prefix is applied explicitly in `embed_query` below.
    embedder = HuggingFaceEmbeddings(
        model_name=settings.embedding_model,
        model_kwargs={"device": settings.embedding_device},
        encode_kwargs={
            "normalize_embeddings": True,
            "batch_size": settings.embedding_batch_size,
        },
        query_encode_kwargs={"normalize_embeddings": True},
    )

    _check_dimension(len(embedder.embed_query("dimension probe")))
    log.info("embedding_model_ready", model=settings.embedding_model)
    return embedder


# ---------------------------------------------------------------------------
# Hosted backend (HuggingFace Inference API)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_inference_client():
    """Return a cached HuggingFace Inference client."""
    from huggingface_hub import InferenceClient

    log.info("using_hf_inference_api", model=settings.embedding_model)
    # `or None` lets InferenceClient fall back to a cached `hf auth login` token, which
    # is how this works on a developer machine. Streamlit Cloud has no such cache, so
    # streamlit_app.py requires HF_TOKEN as a secret there.
    return InferenceClient(token=settings.hf_token or None)


def _hf_embed(text: str) -> list[float]:
    """Embed one string through the Inference API, normalised.

    The endpoint returns either a flat vector or a nested one depending on the model's
    pooling configuration, so the result is flattened defensively rather than indexed
    with an assumption about its shape.
    """
    try:
        output = get_inference_client().feature_extraction(text, model=settings.embedding_model)
    except Exception as exc:  # noqa: BLE001 - re-raised below with actionable guidance
        message = str(exc)
        if "403" in message or "permission" in message.lower():
            # A plain "read" token is NOT enough: HuggingFace gates the Inference API
            # behind its own permission, and the raw 403 says nothing about which box
            # to tick. This is the single most likely deployment failure, so it is
            # worth translating.
            raise RuntimeError(
                "HuggingFace rejected the token (403). A read-only token is not "
                "sufficient for the Inference API: create a fine-grained token at "
                "https://huggingface.co/settings/tokens with 'Make calls to Inference "
                "Providers' enabled, then update the HF_TOKEN secret. Alternatively set "
                "EMBEDDING_BACKEND=local to embed in-process instead."
            ) from exc
        raise

    vector = output.tolist() if hasattr(output, "tolist") else list(output)
    while vector and isinstance(vector[0], list):
        vector = vector[0]

    _check_dimension(len(vector))
    return _normalise([float(x) for x in vector])


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------
def using_hosted_embeddings() -> bool:
    """Whether queries are embedded remotely rather than in this process."""
    return settings.embedding_backend == "hf_api"


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed passages. No instruction prefix -- BGE is trained without one on passages.

    Ingestion runs on a developer machine, so the local backend is the normal path here;
    the hosted branch exists so the two backends stay genuinely interchangeable.
    """
    if using_hosted_embeddings():
        return [_hf_embed(text) for text in texts]
    return get_embedder().embed_documents(texts)


@lru_cache(maxsize=512)
def _embed_query_cached(text: str) -> tuple[float, ...]:
    """Embed one query, memoised. Returns a tuple so it is hashable and immutable."""
    prefixed = f"{_query_instruction_for(settings.embedding_model)}{text}"

    if using_hosted_embeddings():
        return tuple(_hf_embed(prefixed))
    return tuple(get_embedder().embed_query(prefixed))


def embed_query(text: str) -> list[float]:
    """Embed a search query, prefixed with the model's retrieval instruction.

    Results are memoised because embedding is deterministic and the same query is
    frequently re-embedded: the retrieval benchmark sweeps configurations over the same
    questions, and the agent's retry loop re-searches related text. With the hosted
    backend this also removes redundant network round trips. A fresh list is returned each
    call so callers cannot mutate the cached vector.
    """
    return list(_embed_query_cached(text))


def warm_up() -> None:
    """Prepare whichever backend is configured, so the first request is not slow."""
    if using_hosted_embeddings():
        get_inference_client()
        embed_query("warm up")
    else:
        get_embedder()
