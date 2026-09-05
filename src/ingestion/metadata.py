"""Chunk metadata enrichment.

Adds the fields retrieval and citation depend on:

``chunk_id``
    Deterministic identifier, ``sha1(source:chunk_index)``. Deterministic ids make
    re-ingestion idempotent (an upsert overwrites rather than duplicating) and give the
    evaluation golden set a stable handle to assert relevance against.
``chunk_index``
    Position within the parent document, used for ordering and for the id.
``section``
    The nearest preceding markdown heading. This is what turns a citation from
    "deployment_runbook.md" into "deployment_runbook.md > Rollback", and it is also
    prepended to the embedded text so a chunk carries its own context.
``category``
    Inherited from the parent document; this is the field Pinecone filters on.
"""

from __future__ import annotations

import hashlib
import re
from bisect import bisect_right

from langchain_core.documents import Document

from src.config import CATEGORIES
from src.logging_conf import get_logger

log = get_logger(__name__)

# Matches markdown ATX headings at levels 2-4. Level 1 is the document title and is
# already captured as `doc_title`.
_HEADING_RE = re.compile(r"^(#{2,4})\s+(.+?)\s*$", flags=re.MULTILINE)

# PDF extraction loses the '#' markers, so headings are recovered heuristically: a short
# standalone line, in title case, with no terminal punctuation.
_PDF_HEADING_RE = re.compile(r"^(?!.*[.:;,])([A-Z][^\n]{2,60})$", flags=re.MULTILINE)


def make_chunk_id(source: str, chunk_index: int) -> str:
    """Return the deterministic chunk identifier for a source path and position."""
    digest = hashlib.sha1(f"{source}:{chunk_index}".encode()).hexdigest()
    return digest[:24]


def _heading_offsets(text: str, *, is_pdf: bool) -> list[tuple[int, str]]:
    """Return ``(character_offset, heading_text)`` pairs, ascending by offset."""
    pattern = _PDF_HEADING_RE if is_pdf else _HEADING_RE
    offsets: list[tuple[int, str]] = []

    for match in pattern.finditer(text):
        heading = match.group(2) if not is_pdf else match.group(1)
        offsets.append((match.start(), heading.strip()))

    return offsets


def _section_for_offset(offsets: list[tuple[int, str]], start_index: int) -> str:
    """Find the heading immediately preceding ``start_index``.

    Uses binary search over the precomputed heading offsets, so enriching N chunks of a
    document with H headings costs O(N log H) rather than rescanning the text per chunk.
    """
    if not offsets:
        return ""

    positions = [offset for offset, _ in offsets]
    idx = bisect_right(positions, start_index) - 1
    return offsets[idx][1] if idx >= 0 else ""


def infer_category(source: str) -> str:
    """Infer the category from the source path's leading directory.

    Documents outside a known category directory are labelled ``general`` rather than
    guessed at, so a mislabelled chunk never silently pollutes a filtered search.
    """
    top = source.split("/", 1)[0]
    return top if top in CATEGORIES else "general"


def contextualize(chunk_text: str, doc_title: str, section: str) -> str:
    """Prepend the document title and section to the text that gets embedded.

    A chunk taken from the middle of a document often has no self-contained subject --
    "Hold the canary for a minimum of 15 minutes" says nothing about deployment. Adding
    the title and section gives the embedding that subject, and is one of the retrieval
    optimizations the benchmark measures.
    """
    # PDF heading recovery can pick the title line up as a "section" too; don't repeat it.
    if not section or section.strip().lower() == doc_title.strip().lower():
        header = doc_title
    else:
        header = f"{doc_title} > {section}"
    return f"{header}\n\n{chunk_text}" if header else chunk_text


def enrich_chunks(
    chunks: list[Document],
    documents: list[Document],
    *,
    add_context_header: bool = True,
) -> list[Document]:
    """Attach identity and section metadata to chunks, in place.

    Args:
        chunks: Chunks produced by :func:`src.ingestion.chunker.chunk_documents`,
            each carrying ``source``, ``category``, ``doc_title`` and ``start_index``.
        documents: The parent documents the chunks were split from. Needed because
            section lookup resolves each chunk's ``start_index`` against the *original*
            text; inferring it from the chunks alone is unreliable once overlap and
            whitespace stripping have shifted offsets.
        add_context_header: Whether to prepend the title/section header to the embedded
            text. The benchmark's baseline arm sets this to ``False``.

    Returns:
        The same chunk objects, with metadata populated.
    """
    parent_text: dict[str, str] = {
        doc.metadata.get("source", "unknown"): doc.page_content for doc in documents
    }

    # Heading tables are computed once per source document rather than per chunk.
    heading_cache: dict[str, list[tuple[int, str]]] = {}
    per_source_counter: dict[str, int] = {}
    enriched_without_section = 0

    for chunk in chunks:
        meta = chunk.metadata
        source = meta.get("source", "unknown")
        start_index = int(meta.get("start_index", 0))

        if source not in heading_cache:
            heading_cache[source] = _heading_offsets(
                parent_text.get(source, ""),
                is_pdf=meta.get("file_type") == "pdf",
            )

        index = per_source_counter.get(source, 0)
        per_source_counter[source] = index + 1

        section = _section_for_offset(heading_cache[source], start_index)
        if not section:
            enriched_without_section += 1

        meta["chunk_index"] = index
        meta["chunk_id"] = make_chunk_id(source, index)
        meta["section"] = section
        meta["category"] = meta.get("category") or infer_category(source)
        meta["char_count"] = len(chunk.page_content)

        if add_context_header:
            chunk.page_content = contextualize(
                chunk.page_content, meta.get("doc_title", ""), section
            )

    log.info(
        "chunks_enriched",
        chunks=len(chunks),
        sources=len(per_source_counter),
        without_section=enriched_without_section,
        context_header=add_context_header,
    )
    return chunks
