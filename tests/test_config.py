"""Phase 1 smoke tests: the scaffold is importable and the config contract holds."""

import pytest
from pydantic import ValidationError

from src.config import CATEGORIES, PROJECT_ROOT, RAW_DATA_DIR, Settings, settings


def test_project_paths_resolve():
    assert PROJECT_ROOT.is_dir()
    assert (PROJECT_ROOT / "requirements.txt").is_file()
    assert RAW_DATA_DIR.is_dir()


def test_corpus_directories_match_categories():
    """Each category in the taxonomy must have a corresponding corpus directory."""
    for category in CATEGORIES:
        assert (RAW_DATA_DIR / category).is_dir(), f"missing data/raw/{category}"


def test_defaults_are_free_tier_compatible():
    assert settings.embedding_dim == 384, "bge-small-en-v1.5 emits 384-dim vectors"
    assert settings.pinecone_region == "us-east-1", "only region on the Pinecone free tier"
    assert settings.pinecone_namespace != settings.pinecone_baseline_namespace


def test_chunk_overlap_must_be_smaller_than_chunk_size():
    with pytest.raises(ValidationError):
        Settings(chunk_size=200, chunk_overlap=200)


def test_mmr_lambda_bounded():
    with pytest.raises(ValidationError):
        Settings(retrieval_mmr_lambda=1.5)


def test_missing_credentials_fail_loudly_not_silently():
    """Importing must never require keys, but *using* a provider must say so clearly."""
    blank = Settings(groq_api_key="", pinecone_api_key="")
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        blank.require_groq()
    with pytest.raises(RuntimeError, match="PINECONE_API_KEY"):
        blank.require_pinecone()
