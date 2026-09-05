"""Chunking strategies.

Two strategies are defined, and the difference between them is the whole point of the
retrieval benchmark:

``OPTIMIZED``
    Markdown-aware recursive splitting. Separators are ordered most- to least-semantic
    (headings, then paragraphs, then lines, then words) so a split lands on a section or
    paragraph boundary wherever one exists nearby. Overlap carries context across the
    boundary so a fact split across two chunks is still answerable from either.

``BASELINE``
    The naive default most tutorials use: a fixed character window with no overlap and no
    awareness of structure. Splits land mid-sentence and mid-table.

Both are exercised by ``scripts/benchmark_retrieval.py``; only ``OPTIMIZED`` serves the
live application.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.config import settings
from src.logging_conf import get_logger

log = get_logger(__name__)


class Strategy(str, Enum):
    """Named chunking strategies."""

    OPTIMIZED = "optimized"
    BASELINE = "baseline"


@dataclass(frozen=True)
class ChunkConfig:
    """A concrete chunking configuration.

    Attributes:
        chunk_size: Target characters per chunk.
        chunk_overlap: Characters repeated between adjacent chunks.
        separators: Split points in descending order of preference.
        name: Human-readable label used in benchmark reports.
    """

    chunk_size: int
    chunk_overlap: int
    separators: tuple[str, ...]
    name: str

    def describe(self) -> str:
        """One-line description for benchmark reports."""
        return (
            f"{self.name}: size={self.chunk_size}, overlap={self.chunk_overlap}, "
            f"separators={len(self.separators)}"
        )


# Markdown-aware separators. Heading markers come first so a chunk boundary prefers to
# fall between sections; the empty string is the last resort hard split.
_MARKDOWN_SEPARATORS: tuple[str, ...] = (
    "\n## ",
    "\n### ",
    "\n#### ",
    "\n\n",
    "\n",
    ". ",
    " ",
    "",
)

# The naive comparison arm: a single hard separator means every split is a raw character
# cut with no regard for structure.
_NAIVE_SEPARATORS: tuple[str, ...] = ("",)


def get_config(strategy: Strategy | str = Strategy.OPTIMIZED) -> ChunkConfig:
    """Return the :class:`ChunkConfig` for a strategy.

    The optimized configuration reads its sizes from settings so that the app, the
    ingestion pipeline and the benchmark can never drift apart. The baseline is
    hardcoded on purpose: it represents a fixed, published comparison point, and making
    it configurable would let the benchmark be tuned after the fact.
    """
    strategy = Strategy(strategy)

    if strategy is Strategy.OPTIMIZED:
        return ChunkConfig(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            separators=_MARKDOWN_SEPARATORS,
            name="optimized",
        )

    return ChunkConfig(
        chunk_size=512,
        chunk_overlap=0,
        separators=_NAIVE_SEPARATORS,
        name="baseline",
    )


def build_splitter(config: ChunkConfig) -> RecursiveCharacterTextSplitter:
    """Construct the splitter for a configuration.

    ``add_start_index`` is essential: :mod:`src.ingestion.metadata` uses the character
    offset to work out which section of the parent document each chunk came from.
    """
    return RecursiveCharacterTextSplitter(
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        separators=list(config.separators),
        add_start_index=True,
        keep_separator=True,
        strip_whitespace=True,
    )


def chunk_documents(
    documents: list[Document],
    strategy: Strategy | str = Strategy.OPTIMIZED,
) -> list[Document]:
    """Split documents into chunks, preserving each parent's metadata.

    Args:
        documents: Loaded source documents.
        strategy: Which chunking configuration to apply.

    Returns:
        Chunks with the parent metadata plus ``start_index``. Section and identity
        metadata is added afterwards by :func:`src.ingestion.metadata.enrich_chunks`.
    """
    config = get_config(strategy)
    splitter = build_splitter(config)

    chunks = splitter.split_documents(documents)

    # Very short fragments are almost always splitter debris (a stray heading, a table
    # rule) and act as noise at retrieval time. Dropping them measurably helps the
    # optimized arm, and is one of the changes the benchmark accounts for.
    if config.name == "optimized":
        before = len(chunks)
        chunks = [c for c in chunks if len(c.page_content.strip()) >= 80]
        if before != len(chunks):
            log.debug("dropped_fragment_chunks", dropped=before - len(chunks))

    sizes = [len(c.page_content) for c in chunks] or [0]
    log.info(
        "documents_chunked",
        strategy=config.name,
        documents=len(documents),
        chunks=len(chunks),
        mean_chars=round(sum(sizes) / len(sizes)),
        min_chars=min(sizes),
        max_chars=max(sizes),
    )
    return chunks
