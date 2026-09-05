"""End-to-end ingestion: load -> chunk -> enrich -> embed -> upsert.

The same function ingests both benchmark arms; only the strategy and namespace differ.
Keeping them on one code path is what makes the A/B comparison honest -- the arms cannot
accidentally diverge in some step unrelated to what is being measured.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.documents import Document

from src.config import RAW_DATA_DIR, settings
from src.ingestion.chunker import Strategy, chunk_documents, get_config
from src.ingestion.loaders import load_corpus
from src.ingestion.metadata import enrich_chunks
from src.logging_conf import get_logger
from src.retrieval.embedder import embed_texts
from src.retrieval.vector_store import clear_namespace, ensure_index, upsert_documents

log = get_logger(__name__)


@dataclass
class IngestionResult:
    """Summary of one ingestion run."""

    strategy: str
    namespace: str
    documents: int
    chunks: int
    vectors_upserted: int
    chunks_by_category: dict[str, int] = field(default_factory=dict)
    mean_chunk_chars: int = 0

    def summary(self) -> str:
        """Human-readable one-paragraph summary for CLI output."""
        by_category = ", ".join(f"{k}={v}" for k, v in sorted(self.chunks_by_category.items()))
        return (
            f"[{self.strategy}] namespace={self.namespace}  "
            f"{self.documents} documents -> {self.chunks} chunks "
            f"(mean {self.mean_chunk_chars} chars; {by_category})  "
            f"{self.vectors_upserted} vectors upserted"
        )


def ingest(
    *,
    strategy: Strategy | str = Strategy.OPTIMIZED,
    namespace: str | None = None,
    corpus_root: Path = RAW_DATA_DIR,
    reset: bool = True,
    documents: list[Document] | None = None,
) -> IngestionResult:
    """Run the full ingestion pipeline for one strategy.

    Args:
        strategy: ``OPTIMIZED`` (serves the app) or ``BASELINE`` (benchmark only).
        namespace: Pinecone namespace. Defaults to the namespace matching the strategy.
        corpus_root: Corpus directory to load from.
        reset: Clear the namespace first. On by default so a shortened or renamed source
            document cannot leave orphaned, still-retrievable chunks behind.
        documents: Pre-loaded documents, to avoid re-reading the corpus when ingesting
            both arms in one process.

    Returns:
        An :class:`IngestionResult` describing what was written.
    """
    strategy = Strategy(strategy)
    config = get_config(strategy)

    if namespace is None:
        namespace = (
            settings.pinecone_namespace
            if strategy is Strategy.OPTIMIZED
            else settings.pinecone_baseline_namespace
        )

    log.info(
        "ingestion_started", strategy=config.name, namespace=namespace, config=config.describe()
    )

    # 1. Load ------------------------------------------------------------------
    documents = documents if documents is not None else load_corpus(corpus_root)

    # 2. Chunk -----------------------------------------------------------------
    chunks = chunk_documents(documents, strategy)

    # 3. Enrich ----------------------------------------------------------------
    # The baseline arm gets identity metadata (it needs chunk_ids to be scored against
    # the golden set) but no contextual header -- that header is one of the optimizations
    # under measurement, so giving it to both arms would understate the difference.
    enrich_chunks(chunks, documents, add_context_header=strategy is Strategy.OPTIMIZED)

    # 4. Embed -----------------------------------------------------------------
    log.info("embedding_chunks", chunks=len(chunks))
    vectors = embed_texts([chunk.page_content for chunk in chunks])

    # 5. Upsert ----------------------------------------------------------------
    index = ensure_index()
    if reset:
        clear_namespace(namespace, index=index)

    upserted = upsert_documents(chunks, vectors, namespace=namespace, index=index)

    by_category: dict[str, int] = {}
    for chunk in chunks:
        category = chunk.metadata.get("category", "general")
        by_category[category] = by_category.get(category, 0) + 1

    sizes = [chunk.metadata.get("char_count", 0) for chunk in chunks] or [0]

    result = IngestionResult(
        strategy=config.name,
        namespace=namespace,
        documents=len(documents),
        chunks=len(chunks),
        vectors_upserted=upserted,
        chunks_by_category=by_category,
        mean_chunk_chars=round(sum(sizes) / len(sizes)),
    )
    log.info(
        "ingestion_complete",
        **{k: v for k, v in result.__dict__.items() if k != "chunks_by_category"},
    )
    return result


def ingest_both_arms(corpus_root: Path = RAW_DATA_DIR) -> list[IngestionResult]:
    """Ingest the optimized and baseline arms, loading the corpus only once."""
    documents = load_corpus(corpus_root)
    return [
        ingest(strategy=Strategy.OPTIMIZED, documents=documents, corpus_root=corpus_root),
        ingest(strategy=Strategy.BASELINE, documents=documents, corpus_root=corpus_root),
    ]
