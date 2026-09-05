"""Local embedding model.

Uses ``BAAI/bge-small-en-v1.5`` through sentence-transformers. It runs on the local CPU,
so embedding costs nothing and works offline once the ~130 MB model is cached.

Two details that matter for retrieval quality with BGE models:

1. **Normalised vectors.** BGE is trained for cosine similarity, and the Pinecone index
   is created with ``metric="cosine"``. Normalising at encode time also means the dot
   product equals cosine, which keeps the MMR maths below straightforward.
2. **An asymmetric query prefix.** BGE was trained with the instruction
   ``"Represent this sentence for searching relevant passages: "`` prepended to *queries*
   but not to passages. Omitting it costs a few points of retrieval accuracy, and it is
   the single most commonly missed detail when people adopt these models.
"""

from __future__ import annotations

from functools import lru_cache

from langchain_huggingface import HuggingFaceEmbeddings

from src.config import settings
from src.logging_conf import get_logger

log = get_logger(__name__)

# The instruction prefix BGE v1.5 English models were trained with, applied to queries
# only. See the model card on the HuggingFace hub.
BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


def _query_instruction_for(model_name: str) -> str:
    """Return the query prefix appropriate to the model, or an empty string."""
    return BGE_QUERY_INSTRUCTION if "bge" in model_name.lower() else ""


@lru_cache(maxsize=1)
def get_embedder() -> HuggingFaceEmbeddings:
    """Return the process-wide embedding model.

    Cached because loading sentence-transformers takes several seconds and allocates a
    few hundred megabytes; the FastAPI app must not pay that per request.
    """
    log.info(
        "loading_embedding_model",
        model=settings.embedding_model,
        device=settings.embedding_device,
    )

    # NOTE: langchain-huggingface 1.x dropped the `query_instruction` field that 0.x
    # had, so the BGE prefix is applied explicitly in `embed_query` below rather than
    # being delegated to the wrapper.
    embedder = HuggingFaceEmbeddings(
        model_name=settings.embedding_model,
        model_kwargs={"device": settings.embedding_device},
        encode_kwargs={
            "normalize_embeddings": True,
            "batch_size": settings.embedding_batch_size,
        },
        query_encode_kwargs={"normalize_embeddings": True},
    )

    # Fail fast and loudly if the configured dimension does not match reality; a
    # mismatch otherwise surfaces much later as an opaque Pinecone upsert error.
    actual_dim = len(embedder.embed_query("dimension probe"))
    if actual_dim != settings.embedding_dim:
        raise RuntimeError(
            f"EMBEDDING_DIM is {settings.embedding_dim} but {settings.embedding_model} "
            f"produces {actual_dim}-dimensional vectors. Update .env and recreate the "
            "Pinecone index -- an index's dimension cannot be changed in place."
        )

    log.info("embedding_model_ready", model=settings.embedding_model, dim=actual_dim)
    return embedder


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed passages. No instruction prefix -- BGE was trained without one on passages."""
    return get_embedder().embed_documents(texts)


@lru_cache(maxsize=512)
def _embed_query_cached(text: str) -> tuple[float, ...]:
    """Embed one query, memoised. Returns a tuple so it is hashable and immutable."""
    prefix = _query_instruction_for(settings.embedding_model)
    return tuple(get_embedder().embed_query(f"{prefix}{text}"))


def embed_query(text: str) -> list[float]:
    """Embed a search query, prefixed with the model's retrieval instruction.

    The prefix is applied here rather than in the wrapper because langchain-huggingface
    1.x no longer accepts a ``query_instruction`` argument. Skipping it still "works" --
    it just quietly costs retrieval accuracy, which is why it is centralised in this one
    function that every caller goes through.

    Results are memoised because embedding is deterministic and the same query is
    frequently re-embedded: the retrieval benchmark sweeps 28 configurations over the
    same questions, and the agent's retry loop re-searches related text. A fresh list is
    returned each call so callers cannot mutate the cached vector.
    """
    return list(_embed_query_cached(text))
