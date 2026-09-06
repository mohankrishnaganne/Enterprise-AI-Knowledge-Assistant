"""Embedding backend selection.

The two backends must stay genuinely interchangeable: the deployed Streamlit app uses
the hosted one while the Pinecone index was built with the local one, so any divergence
in normalisation or in the BGE query prefix would silently degrade retrieval against an
index that still looks fine. These run offline with the network mocked.
"""

from __future__ import annotations

import math

import pytest

from src.retrieval import embedder


@pytest.fixture(autouse=True)
def _clear_caches():
    """Backend choice is read at call time, but results are memoised; reset between tests."""
    embedder._embed_query_cached.cache_clear()
    embedder.get_inference_client.cache_clear()
    yield
    embedder._embed_query_cached.cache_clear()
    embedder.get_inference_client.cache_clear()


class FakeInferenceClient:
    """Records what was sent to the Inference API and returns a fixed unnormalised vector."""

    def __init__(self, output=None):
        self.calls: list[str] = []
        self.output = output if output is not None else [3.0, 4.0] + [0.0] * 382

    def feature_extraction(self, text, model=None):
        self.calls.append(text)
        return self.output


def use_hosted(monkeypatch, client):
    """Point the embedder at the hosted backend with a fake client."""
    monkeypatch.setattr(embedder.settings, "embedding_backend", "hf_api")
    monkeypatch.setattr(embedder, "get_inference_client", lambda: client)


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------
def test_backend_defaults_to_local():
    assert embedder.settings.embedding_backend == "local"
    assert embedder.using_hosted_embeddings() is False


def test_hosted_backend_is_detected(monkeypatch):
    monkeypatch.setattr(embedder.settings, "embedding_backend", "hf_api")
    assert embedder.using_hosted_embeddings() is True


def test_hosted_query_never_loads_the_local_model(monkeypatch):
    """The whole point of the hosted backend is that torch need not be installed."""
    client = FakeInferenceClient()
    use_hosted(monkeypatch, client)

    def explode():
        raise AssertionError("the local model must not be loaded on the hosted backend")

    monkeypatch.setattr(embedder, "get_embedder", explode)
    embedder.embed_query("anything")


# ---------------------------------------------------------------------------
# Parity between the backends
# ---------------------------------------------------------------------------
def test_hosted_vectors_are_normalised(monkeypatch):
    """The index uses cosine and MMR treats the dot product as cosine, so this matters."""
    client = FakeInferenceClient()
    use_hosted(monkeypatch, client)

    vector = embedder.embed_query("test")
    assert math.isclose(math.sqrt(sum(x * x for x in vector)), 1.0, rel_tol=1e-6)
    # 3-4-5 triangle: the fixture's raw vector normalises to 0.6, 0.8.
    assert math.isclose(vector[0], 0.6, rel_tol=1e-6)
    assert math.isclose(vector[1], 0.8, rel_tol=1e-6)


def test_hosted_query_gets_the_bge_instruction_prefix(monkeypatch):
    """Omitting the prefix embeds queries into the wrong region of the space."""
    client = FakeInferenceClient()
    use_hosted(monkeypatch, client)

    embedder.embed_query("what is the rate limit")
    assert client.calls[0].startswith(embedder.BGE_QUERY_INSTRUCTION)
    assert client.calls[0].endswith("what is the rate limit")


def test_hosted_passages_do_not_get_the_prefix(monkeypatch):
    """BGE is trained with the instruction on queries only."""
    client = FakeInferenceClient()
    use_hosted(monkeypatch, client)

    embedder.embed_texts(["a passage of documentation"])
    assert not client.calls[0].startswith(embedder.BGE_QUERY_INSTRUCTION)


def test_hosted_response_is_flattened(monkeypatch):
    """The endpoint may return [[...]] or [...] depending on pooling configuration."""
    nested = FakeInferenceClient(output=[[[1.0] + [0.0] * 383]])
    use_hosted(monkeypatch, nested)
    assert len(embedder.embed_query("test")) == 384


def test_queries_are_memoised(monkeypatch):
    """Embedding is deterministic; with the hosted backend this also saves round trips."""
    client = FakeInferenceClient()
    use_hosted(monkeypatch, client)

    embedder.embed_query("same question")
    embedder.embed_query("same question")
    assert len(client.calls) == 1


def test_embed_query_returns_a_fresh_list(monkeypatch):
    """Callers must not be able to mutate the cached vector."""
    client = FakeInferenceClient()
    use_hosted(monkeypatch, client)

    first = embedder.embed_query("q")
    first[0] = 999.0
    assert embedder.embed_query("q")[0] != 999.0


# ---------------------------------------------------------------------------
# Dimension safety
# ---------------------------------------------------------------------------
def test_wrong_dimension_fails_loudly(monkeypatch):
    """A Pinecone index's dimension is immutable, so this must fail before upsert."""
    client = FakeInferenceClient(output=[1.0, 0.0, 0.0])
    use_hosted(monkeypatch, client)

    with pytest.raises(RuntimeError, match="EMBEDDING_DIM"):
        embedder.embed_query("test")
