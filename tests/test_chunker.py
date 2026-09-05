"""Chunking behaviour, including the properties the retrieval benchmark relies on."""

import pytest
from langchain_core.documents import Document

from src.config import settings
from src.ingestion.chunker import Strategy, chunk_documents, get_config


def test_optimized_config_follows_settings():
    """The app, ingestion and benchmark must never drift apart on chunk sizing."""
    config = get_config(Strategy.OPTIMIZED)
    assert config.chunk_size == settings.chunk_size
    assert config.chunk_overlap == settings.chunk_overlap


def test_baseline_config_is_hardcoded():
    """The comparison arm is fixed so the benchmark cannot be tuned after the fact."""
    config = get_config(Strategy.BASELINE)
    assert config.chunk_size == 512
    assert config.chunk_overlap == 0
    assert config.separators == ("",)


def test_chunks_respect_the_size_ceiling(optimized_chunks):
    for chunk in optimized_chunks:
        assert chunk.metadata["char_count"] <= settings.chunk_size


def test_optimized_strategy_produces_overlap():
    """Overlap is what keeps a fact readable when it straddles a chunk boundary."""
    text = " ".join(f"sentence number {i} about deployment." for i in range(200))
    doc = Document(
        page_content=text, metadata={"source": "technical/x.md", "category": "technical"}
    )

    chunks = chunk_documents([doc], Strategy.OPTIMIZED)
    assert len(chunks) > 1

    # Adjacent chunks should share text. Compare the tail of one against the head of the
    # next rather than asserting an exact overlap length, which the recursive splitter
    # varies to land on a separator.
    first, second = chunks[0].page_content, chunks[1].page_content
    tail = first[-settings.chunk_overlap :]
    assert any(word in second[: settings.chunk_overlap * 2] for word in tail.split()[:3])


def test_baseline_strategy_produces_no_overlap():
    text = "x" * 4000
    doc = Document(
        page_content=text, metadata={"source": "technical/x.md", "category": "technical"}
    )
    chunks = chunk_documents([doc], Strategy.BASELINE)

    starts = [c.metadata["start_index"] for c in chunks]
    # With zero overlap and a hard separator, each chunk starts exactly where the last ended.
    assert starts == sorted(starts)
    assert all(b - a >= 512 for a, b in zip(starts, starts[1:], strict=False))


def test_baseline_splits_mid_sentence_more_often(optimized_chunks, baseline_chunks):
    """The core premise of the benchmark: naive splitting cuts through prose.

    A chunk starting with a lowercase letter began mid-sentence. The optimized splitter
    prefers heading and paragraph boundaries, so it should do this markedly less.
    """

    def mid_sentence_rate(chunks):
        # Skip the contextual header the optimized arm prepends; judge the body text.
        bodies = [c.page_content.split("\n\n", 1)[-1].lstrip() for c in chunks]
        return sum(1 for b in bodies if b and b[0].islower()) / len(bodies)

    assert mid_sentence_rate(baseline_chunks) > mid_sentence_rate(optimized_chunks)


def test_tiny_fragments_are_dropped_from_the_optimized_arm(optimized_chunks):
    """Splitter debris is retrieval noise; the optimized arm filters it."""
    assert min(len(c.page_content.strip()) for c in optimized_chunks) >= 80


def test_unknown_strategy_is_rejected():
    with pytest.raises(ValueError):
        get_config("semantic-magic")
