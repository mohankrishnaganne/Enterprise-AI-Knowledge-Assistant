"""Metadata enrichment: identity, sections, categories and the context header."""

from langchain_core.documents import Document

from src.config import CATEGORIES
from src.ingestion.chunker import Strategy, chunk_documents
from src.ingestion.metadata import (
    contextualize,
    enrich_chunks,
    infer_category,
    make_chunk_id,
)


def test_chunk_ids_are_deterministic():
    """Re-ingestion must overwrite, not duplicate; that requires stable ids."""
    assert make_chunk_id("technical/api_reference.md", 3) == make_chunk_id(
        "technical/api_reference.md", 3
    )
    assert make_chunk_id("technical/api_reference.md", 3) != make_chunk_id(
        "technical/api_reference.md", 4
    )
    assert make_chunk_id("a.md", 0) != make_chunk_id("b.md", 0)


def test_chunk_ids_are_unique_across_the_corpus(optimized_chunks):
    ids = [c.metadata["chunk_id"] for c in optimized_chunks]
    assert len(set(ids)) == len(ids)


def test_every_chunk_carries_the_filterable_fields(optimized_chunks):
    """`category` is the Pinecone filter key; missing it would silently break routing."""
    for chunk in optimized_chunks:
        meta = chunk.metadata
        assert meta["category"] in CATEGORIES
        assert meta["source"]
        assert meta["doc_title"]
        assert isinstance(meta["chunk_index"], int)
        assert meta["chunk_id"]


def test_category_matches_the_source_directory(optimized_chunks):
    for chunk in optimized_chunks:
        assert chunk.metadata["source"].startswith(chunk.metadata["category"] + "/")


def test_infer_category_falls_back_rather_than_guessing():
    assert infer_category("technical/api_reference.md") == "technical"
    assert infer_category("business/pricing.md") == "business"
    # An unknown directory must not be silently assigned to a real category, or a
    # filtered search would return documents it should never see.
    assert infer_category("misc/notes.md") == "general"
    assert infer_category("loose_file.md") == "general"


def test_sections_are_resolved_for_most_chunks(optimized_chunks):
    """Chunks before the first H2 legitimately have no section; most should have one."""
    with_section = sum(1 for c in optimized_chunks if c.metadata["section"])
    assert with_section / len(optimized_chunks) > 0.7


def test_section_comes_from_the_preceding_heading():
    text = (
        "# Runbook\n\n"
        "Intro paragraph before any section heading.\n\n"
        "## Canary\n\n" + "Canary body text. " * 60 + "\n\n"
        "## Rollback\n\n" + "Rollback body text. " * 60
    )
    doc = Document(
        page_content=text,
        metadata={
            "source": "technical/deployment_runbook.md",
            "category": "technical",
            "doc_title": "Runbook",
            "file_type": "md",
        },
    )
    chunks = enrich_chunks(chunk_documents([doc], Strategy.OPTIMIZED), [doc])

    sections = [c.metadata["section"] for c in chunks]
    assert "Canary" in sections
    assert "Rollback" in sections
    # Section order must follow document order.
    assert sections.index("Canary") < sections.index("Rollback")


def test_pdf_sections_are_recovered(optimized_chunks):
    """PDF extraction loses '#' markers, so sections come from a heading heuristic."""
    pdf_chunks = [c for c in optimized_chunks if c.metadata["file_type"] == "pdf"]
    assert pdf_chunks, "corpus should contain PDFs; run scripts/generate_corpus.py"
    assert all(c.metadata["section"] for c in pdf_chunks)


def test_context_header_gives_a_chunk_its_subject(optimized_chunks):
    """A mid-document chunk has no self-contained subject without this header."""
    sample = next(c for c in optimized_chunks if c.metadata["section"])
    assert sample.page_content.startswith(sample.metadata["doc_title"])
    assert sample.metadata["section"] in sample.page_content.split("\n\n", 1)[0]


def test_context_header_does_not_repeat_the_title():
    assert contextualize("body", "Support SLA", "Support SLA") == "Support SLA\n\nbody"
    assert contextualize("body", "Support SLA", "Uptime") == "Support SLA > Uptime\n\nbody"


def test_baseline_arm_has_no_context_header(baseline_chunks):
    """The header is an optimization under measurement; the baseline must not get it."""
    for chunk in baseline_chunks[:20]:
        title = chunk.metadata["doc_title"]
        assert not chunk.page_content.startswith(f"{title}\n\n")
