"""Corpus loading.

Walks ``data/raw/<category>/`` and turns every markdown or PDF file into a LangChain
``Document`` carrying the metadata the rest of the pipeline depends on.

Markdown is read directly rather than via ``TextLoader`` so the encoding is pinned to
UTF-8 (Windows otherwise defaults to cp1252 and mangles the corpus). PDFs go through
``pypdf``; page text is joined with blank lines so the downstream splitter still sees
paragraph boundaries.
"""

from __future__ import annotations

import re
from pathlib import Path

from langchain_core.documents import Document

from src.config import CATEGORIES, RAW_DATA_DIR
from src.logging_conf import get_logger

log = get_logger(__name__)

SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt", ".pdf"}


class CorpusError(RuntimeError):
    """Raised when the corpus on disk is missing or unusable."""


def _read_markdown(path: Path) -> str:
    """Read a text document as UTF-8, tolerating stray bytes rather than crashing."""
    return path.read_text(encoding="utf-8", errors="replace")


def _read_pdf(path: Path) -> str:
    """Extract text from a PDF, one blank-line-separated block per page."""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    text = "\n\n".join(p for p in pages if p)

    if not text.strip():
        # A scanned/image-only PDF would need OCR; fail loudly rather than silently
        # indexing an empty document that can never be retrieved.
        raise CorpusError(
            f"No extractable text in {path.name}. Image-only PDFs require OCR, which this "
            "pipeline does not perform."
        )
    return text


def _derive_title(text: str, fallback: str) -> str:
    """Use the document's H1 as its title, falling back to a prettified filename."""
    match = re.search(r"^#\s+(.+)$", text, flags=re.MULTILINE)
    if match:
        return match.group(1).strip()

    # PDFs lose the '#' marker during extraction, so the first non-empty line is the
    # next best signal.
    for line in text.splitlines():
        if line.strip():
            return line.strip()

    return fallback.replace("_", " ").replace("-", " ").title()


def load_document(path: Path, *, category: str, root: Path = RAW_DATA_DIR) -> Document:
    """Load a single file into a ``Document`` with base metadata attached."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text = _read_pdf(path)
    elif suffix in SUPPORTED_SUFFIXES:
        text = _read_markdown(path)
    else:
        raise CorpusError(f"Unsupported file type: {path}")

    # Store the path relative to data/raw so citations are stable across machines.
    relative_source = path.relative_to(root).as_posix()

    return Document(
        page_content=text,
        metadata={
            "source": relative_source,
            "category": category,
            "doc_title": _derive_title(text, path.stem),
            "file_type": suffix.lstrip("."),
        },
    )


def load_corpus(root: Path = RAW_DATA_DIR) -> list[Document]:
    """Load every supported document under ``root``, grouped by category directory.

    Args:
        root: Corpus root containing one subdirectory per category.

    Returns:
        One ``Document`` per source file, in a stable sorted order so that ingestion
        runs are reproducible.

    Raises:
        CorpusError: If the corpus directory is missing or contains no documents.
    """
    if not root.is_dir():
        raise CorpusError(f"Corpus directory not found: {root}. Run `make corpus` first.")

    documents: list[Document] = []

    for category in CATEGORIES:
        category_dir = root / category
        if not category_dir.is_dir():
            log.warning("category_directory_missing", category=category, path=str(category_dir))
            continue

        files = sorted(
            p
            for p in category_dir.iterdir()
            if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
        )
        for path in files:
            documents.append(load_document(path, category=category, root=root))

        log.info("category_loaded", category=category, documents=len(files))

    if not documents:
        raise CorpusError(
            f"No documents found under {root}. Run `python scripts/generate_corpus.py` to "
            "create the sample corpus, or add your own files."
        )

    log.info(
        "corpus_loaded",
        documents=len(documents),
        characters=sum(len(d.page_content) for d in documents),
    )
    return documents
