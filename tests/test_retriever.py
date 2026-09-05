"""Retrieval logic: MMR, metadata filters and deduplication.

Pure functions with no network access. These are the pieces the Phase 5 benchmark
attributes its improvement to, so their behaviour is pinned down here rather than only
observed in aggregate.
"""

from __future__ import annotations

import math

from src.retrieval.retriever import (
    RetrievedChunk,
    build_filter,
    deduplicate,
    maximal_marginal_relevance,
)


def unit(vector: list[float]) -> list[float]:
    """L2-normalise, matching what the embedder produces."""
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector]


def chunk(chunk_id: str, values: list[float], score: float = 0.9, source: str = "technical/a.md"):
    """Build a chunk carrying an embedding."""
    return RetrievedChunk(
        chunk_id=chunk_id,
        text=f"text for {chunk_id}",
        source=source,
        category=source.split("/")[0],
        doc_title="Title",
        section="Section",
        score=score,
        values=unit(values),
    )


# ---------------------------------------------------------------------------
# Metadata filters
# ---------------------------------------------------------------------------
def test_build_filter_produces_a_pinecone_expression():
    assert build_filter("technical") == {"category": {"$eq": "technical"}}


def test_build_filter_returns_none_when_uncertain():
    """No filter is the right fallback: a wrong one hides the answer entirely."""
    assert build_filter(None) is None
    assert build_filter("") is None


# ---------------------------------------------------------------------------
# MMR
# ---------------------------------------------------------------------------
def test_mmr_prefers_a_diverse_candidate_over_a_near_duplicate():
    """Plain top-k returns two copies of the same passage; MMR should not.

    Note the geometry matters. Candidates that are near-identical to the *query* all
    score relevance ~1.0, so the redundancy penalty cancels against an equal relevance
    gain and MMR correctly keeps them. The interesting case -- and the realistic one --
    is candidates that are redundant with *each other* while being comparably relevant.
    """
    query = unit([1.0, 0.0, 0.0])
    candidates = [
        chunk("dup_a", [0.80, 0.60, 0.00]),
        chunk("dup_b", [0.81, 0.59, 0.00]),  # nearly identical to dup_a
        chunk("distinct", [0.78, 0.00, 0.63]),  # slightly less relevant, unrelated direction
    ]

    diversified = [
        c.chunk_id for c in maximal_marginal_relevance(query, candidates, k=2, lambda_mult=0.5)
    ]
    relevance_only = [
        c.chunk_id for c in maximal_marginal_relevance(query, candidates, k=2, lambda_mult=1.0)
    ]

    assert "distinct" in diversified, "a diverse candidate should displace a near-duplicate"
    # Proves MMR caused the difference: pure relevance ordering returns both duplicates.
    assert relevance_only == ["dup_b", "dup_a"]
    assert diversified != relevance_only


def test_mmr_with_lambda_one_is_plain_top_k():
    query = unit([1.0, 0.0, 0.0])
    candidates = [
        chunk("best", [1.0, 0.0, 0.0]),
        chunk("second", [0.9, 0.4, 0.0]),
        chunk("third", [0.5, 0.9, 0.0]),
    ]

    selected = maximal_marginal_relevance(query, candidates, k=3, lambda_mult=1.0)
    assert [c.chunk_id for c in selected] == ["best", "second", "third"]


def test_mmr_always_selects_the_most_relevant_candidate_first():
    query = unit([1.0, 0.0, 0.0])
    candidates = [
        chunk("far", [0.2, 1.0, 0.0]),
        chunk("near", [1.0, 0.05, 0.0]),
    ]

    for lambda_mult in (0.0, 0.5, 1.0):
        selected = maximal_marginal_relevance(query, candidates, k=1, lambda_mult=lambda_mult)
        assert selected[0].chunk_id == "near"


def test_mmr_returns_at_most_k_and_never_repeats():
    query = unit([1.0, 0.0, 0.0])
    candidates = [chunk(f"c{i}", [1.0, i / 10, 0.0]) for i in range(6)]

    selected = maximal_marginal_relevance(query, candidates, k=3, lambda_mult=0.5)
    ids = [c.chunk_id for c in selected]

    assert len(ids) == 3
    assert len(set(ids)) == 3


def test_mmr_degrades_to_relevance_order_without_vectors():
    """Missing embeddings must not silently mis-rank; fall back to score order."""
    candidates = [
        RetrievedChunk("a", "t", "technical/a.md", "technical", "T", "S", 0.9),
        RetrievedChunk("b", "t", "technical/a.md", "technical", "T", "S", 0.5),
    ]
    selected = maximal_marginal_relevance([1.0, 0.0], candidates, k=2, lambda_mult=0.5)
    assert [c.chunk_id for c in selected] == ["a", "b"]


def test_mmr_handles_empty_input():
    assert maximal_marginal_relevance([1.0, 0.0], [], k=3, lambda_mult=0.5) == []


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------
def test_deduplicate_keeps_the_highest_scoring_occurrence():
    """Neighbouring sub-queries routinely retrieve the same chunk."""
    merged = deduplicate(
        [
            chunk("shared", [1.0, 0.0, 0.0], score=0.7),
            chunk("shared", [1.0, 0.0, 0.0], score=0.9),
            chunk("other", [0.0, 1.0, 0.0], score=0.6),
        ]
    )

    assert len(merged) == 2
    assert next(c for c in merged if c.chunk_id == "shared").score == 0.9


def test_deduplicate_returns_descending_score_order():
    merged = deduplicate(
        [
            chunk("low", [1.0, 0.0, 0.0], score=0.3),
            chunk("high", [0.0, 1.0, 0.0], score=0.95),
            chunk("mid", [0.0, 0.0, 1.0], score=0.6),
        ]
    )
    assert [c.chunk_id for c in merged] == ["high", "mid", "low"]


# ---------------------------------------------------------------------------
# Citations
# ---------------------------------------------------------------------------
def test_citation_includes_the_section_when_known():
    assert chunk("a", [1.0, 0.0], source="technical/deployment_runbook.md").citation == (
        "deployment_runbook.md > Section"
    )


def test_citation_falls_back_to_the_filename():
    doc = RetrievedChunk("a", "t", "technical/api_reference.md", "technical", "T", "", 0.8)
    assert doc.citation == "api_reference.md"
