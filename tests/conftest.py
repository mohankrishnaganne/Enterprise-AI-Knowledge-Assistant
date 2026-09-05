"""Shared fixtures.

The corpus is loaded once per test session because reading and extracting the PDFs is
the slowest part of these tests, and nothing here mutates the documents.
"""

import pytest

from src.ingestion.chunker import Strategy, chunk_documents
from src.ingestion.loaders import load_corpus
from src.ingestion.metadata import enrich_chunks


@pytest.fixture(scope="session")
def documents():
    """Every source document in data/raw/."""
    return load_corpus()


@pytest.fixture(scope="session")
def optimized_chunks(documents):
    """Enriched chunks from the optimized strategy (what the live app indexes)."""
    chunks = chunk_documents(documents, Strategy.OPTIMIZED)
    return enrich_chunks(chunks, documents, add_context_header=True)


@pytest.fixture(scope="session")
def baseline_chunks(documents):
    """Enriched chunks from the naive baseline strategy (benchmark comparison arm)."""
    chunks = chunk_documents(documents, Strategy.BASELINE)
    return enrich_chunks(chunks, documents, add_context_header=False)
