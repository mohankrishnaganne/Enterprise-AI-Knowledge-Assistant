"""Pinecone serverless client.

Thin wrapper over the Pinecone SDK covering index lifecycle, batched upsert and query.
Deliberately not built on ``PineconeVectorStore`` from ``langchain-pinecone``: the
retriever needs raw scores and full metadata to implement MMR, score thresholding and
the benchmark's per-chunk relevance accounting, and the LangChain wrapper hides those.

Namespaces separate the two benchmark arms (``v1`` optimized, ``baseline`` naive) so the
whole project fits inside the single index the Pinecone free tier allows.
"""

from __future__ import annotations

import itertools
import time
from collections.abc import Iterable, Iterator
from typing import Any

from langchain_core.documents import Document

from src.config import settings
from src.logging_conf import get_logger

log = get_logger(__name__)

# Pinecone accepts up to 1000 vectors per upsert but caps the request at 2 MB. With
# 384-dim float32 vectors plus metadata, 100 per batch stays comfortably under.
UPSERT_BATCH_SIZE = 100

# Metadata values Pinecone can store and filter on. Anything else is dropped before
# upsert rather than triggering an opaque server-side error.
_ALLOWED_METADATA_TYPES = (str, int, float, bool)


def _batched(iterable: Iterable[Any], size: int) -> Iterator[list[Any]]:
    """Yield successive lists of at most ``size`` items."""
    iterator = iter(iterable)
    while batch := list(itertools.islice(iterator, size)):
        yield batch


def get_client():
    """Return an authenticated Pinecone client."""
    from pinecone import Pinecone

    return Pinecone(api_key=settings.require_pinecone())


def ensure_index(*, wait: bool = True):
    """Create the serverless index if it does not exist, then return a handle to it.

    Args:
        wait: Block until the index reports ready. A freshly created serverless index
            takes roughly 10-30 seconds, and upserting before it is ready fails.
    """
    from pinecone import ServerlessSpec

    client = get_client()
    name = settings.pinecone_index_name
    existing = set(client.list_indexes().names())

    if name not in existing:
        log.info(
            "creating_pinecone_index",
            index=name,
            dimension=settings.embedding_dim,
            cloud=settings.pinecone_cloud,
            region=settings.pinecone_region,
        )
        client.create_index(
            name=name,
            dimension=settings.embedding_dim,
            metric="cosine",
            spec=ServerlessSpec(cloud=settings.pinecone_cloud, region=settings.pinecone_region),
        )

        if wait:
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                if client.describe_index(name).status.get("ready"):
                    break
                time.sleep(2)
            else:
                raise TimeoutError(f"Pinecone index {name!r} was not ready within 120s.")
        log.info("pinecone_index_created", index=name)
    else:
        # A pre-existing index with the wrong dimension is a common and confusing
        # failure after changing embedding models. Catch it here with a clear message.
        description = client.describe_index(name)
        if description.dimension != settings.embedding_dim:
            raise RuntimeError(
                f"Pinecone index {name!r} has dimension {description.dimension} but the "
                f"configured embedding model produces {settings.embedding_dim}. Delete the "
                "index in the Pinecone console and re-run ingestion; dimension is immutable."
            )

    return client.Index(name)


def _clean_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Drop metadata values Pinecone cannot store, and never store None."""
    return {
        key: value
        for key, value in metadata.items()
        if value is not None and isinstance(value, _ALLOWED_METADATA_TYPES)
    }


def upsert_documents(
    documents: list[Document],
    embeddings: list[list[float]],
    *,
    namespace: str | None = None,
    index=None,
) -> int:
    """Upsert chunks and their vectors.

    The chunk text is stored in the ``text`` metadata field so retrieval returns usable
    content without a second lookup, which matters because Pinecone is the only store in
    this system -- there is no separate document database.

    Returns:
        The number of vectors upserted.
    """
    if len(documents) != len(embeddings):
        raise ValueError(f"Got {len(documents)} documents but {len(embeddings)} embeddings.")

    index = index or ensure_index()
    namespace = namespace or settings.pinecone_namespace

    vectors = []
    for doc, vector in zip(documents, embeddings, strict=True):
        chunk_id = doc.metadata.get("chunk_id")
        if not chunk_id:
            raise ValueError(
                "Chunk is missing `chunk_id`. Run src.ingestion.metadata.enrich_chunks "
                "before upserting."
            )
        metadata = _clean_metadata(doc.metadata)
        metadata["text"] = doc.page_content
        vectors.append({"id": chunk_id, "values": vector, "metadata": metadata})

    total = 0
    for batch in _batched(vectors, UPSERT_BATCH_SIZE):
        index.upsert(vectors=batch, namespace=namespace)
        total += len(batch)
        log.debug("upsert_batch", namespace=namespace, batch=len(batch), total=total)

    log.info("upsert_complete", namespace=namespace, vectors=total)
    return total


def query(
    vector: list[float],
    *,
    top_k: int,
    namespace: str | None = None,
    metadata_filter: dict[str, Any] | None = None,
    include_values: bool = False,
    index=None,
) -> list[dict[str, Any]]:
    """Run a similarity query.

    Args:
        vector: The query embedding.
        top_k: How many matches to return.
        namespace: Pinecone namespace; defaults to the configured one.
        metadata_filter: Pinecone filter expression, e.g. ``{"category": {"$eq": "technical"}}``.
        include_values: Return each match's stored embedding as ``values``. Required by
            MMR, which needs candidate vectors to measure redundancy between them.
        index: Reusable index handle.

    Returns:
        A list of ``{"id", "score", "metadata"[, "values"]}`` dicts, descending by score.
    """
    index = index or ensure_index()
    namespace = namespace or settings.pinecone_namespace

    response = index.query(
        vector=vector,
        top_k=top_k,
        namespace=namespace,
        include_metadata=True,
        include_values=include_values,
        filter=metadata_filter or None,
    )

    matches = []
    for match in response.get("matches", []):
        entry = {
            "id": match["id"],
            "score": float(match["score"]),
            "metadata": dict(match["metadata"]),
        }
        if include_values:
            entry["values"] = list(match.get("values") or [])
        matches.append(entry)
    log.debug(
        "pinecone_query",
        namespace=namespace,
        top_k=top_k,
        returned=len(matches),
        filter=metadata_filter,
    )
    return matches


def clear_namespace(namespace: str, *, index=None) -> None:
    """Delete every vector in a namespace.

    Used by ingestion's ``--reset`` (the default) so that renaming or shortening a source
    document cannot leave orphaned chunks behind that would still be retrievable.
    """
    index = index or ensure_index()
    try:
        index.delete(delete_all=True, namespace=namespace)
        log.info("namespace_cleared", namespace=namespace)
    except Exception as exc:  # noqa: BLE001 - deleting an absent namespace is not an error
        log.info("namespace_clear_skipped", namespace=namespace, reason=str(exc))


def describe_stats(index=None) -> dict[str, Any]:
    """Return index statistics, including per-namespace vector counts."""
    index = index or ensure_index()
    stats = index.describe_index_stats()
    return {
        "total_vectors": stats.get("total_vector_count", 0),
        "dimension": stats.get("dimension"),
        "namespaces": {
            name: value.get("vector_count", 0)
            for name, value in (stats.get("namespaces") or {}).items()
        },
    }
