"""Retrievers.

Two implementations, matching the two ingestion arms:

:class:`OptimizedRetriever`
    What the live agent uses. Four things separate it from a plain top-k similarity
    search, and each is measured independently by the Phase 5 benchmark:

    1. **Metadata filtering** -- the router's inferred category becomes a Pinecone
       filter, so an HR question never competes against API documentation.
    2. **Over-fetch then MMR** -- fetch ``fetch_k`` candidates and select ``top_k`` by
       Maximal Marginal Relevance, trading a little relevance for coverage.
       **Measured caveat:** on this corpus MMR *hurt*. Only ~1.6 chunks per question
       contain the answer, so there is no breadth to recover and diversity simply
       displaces the best chunk; the benchmark's tuner selected ``lambda=1.0``, which
       is effectively off. It is kept because a corpus with multi-faceted answers would
       benefit, and because turning the knob is a config change rather than a code one.
    3. **Score thresholding** -- drop candidates below a cosine floor rather than
       always returning k results. This turned out to be where nearly all of the
       measured gain comes from. Note the floor is corpus-specific: the original 0.35
       was a no-op here because every bge cosine score sat above it.
    4. **Contextual chunk headers** -- applied at ingestion, but the benefit shows up
       here.

:class:`BaselineRetriever`
    Plain top-k similarity over the naive chunks, with none of the above. It exists
    only so the benchmark has an honest comparison point.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.config import settings
from src.logging_conf import get_logger
from src.retrieval.embedder import embed_query
from src.retrieval.vector_store import query as pinecone_query

log = get_logger(__name__)


@dataclass
class RetrievedChunk:
    """One retrieved chunk, flattened out of the Pinecone match structure."""

    chunk_id: str
    text: str
    source: str
    category: str
    doc_title: str
    section: str
    score: float
    values: list[float] = field(default_factory=list, repr=False)

    # Populated later by the grading node; kept here so one object carries a chunk
    # through the whole graph.
    is_relevant: bool | None = None
    grade_reason: str = ""

    @property
    def citation(self) -> str:
        """Human-readable provenance, e.g. ``deployment_runbook.md > Rollback``."""
        name = self.source.split("/")[-1]
        return f"{name} > {self.section}" if self.section else name

    @classmethod
    def from_match(cls, match: dict[str, Any]) -> RetrievedChunk:
        """Build a chunk from a raw Pinecone match."""
        meta = match.get("metadata", {})
        return cls(
            chunk_id=match["id"],
            text=meta.get("text", ""),
            source=meta.get("source", ""),
            category=meta.get("category", "general"),
            doc_title=meta.get("doc_title", ""),
            section=meta.get("section", ""),
            score=match.get("score", 0.0),
            values=match.get("values", []),
        )


def _dot(a: list[float], b: list[float]) -> float:
    """Dot product. Vectors are L2-normalised at encode time, so this is cosine."""
    return sum(x * y for x, y in zip(a, b, strict=True))


def maximal_marginal_relevance(
    query_vector: list[float],
    candidates: list[RetrievedChunk],
    *,
    k: int,
    lambda_mult: float,
) -> list[RetrievedChunk]:
    """Select ``k`` candidates balancing query relevance against mutual redundancy.

    Standard MMR: repeatedly pick the candidate maximising

        lambda * sim(candidate, query) - (1 - lambda) * max sim(candidate, already_selected)

    ``lambda_mult`` of 1.0 degenerates to plain top-k; 0.0 selects purely for diversity.

    Candidates missing their stored vectors cannot be scored for redundancy, so the
    function falls back to relevance order rather than silently mis-ranking them.
    """
    if not candidates or k <= 0:
        return []
    if any(not c.values for c in candidates):
        log.warning("mmr_skipped_missing_vectors", candidates=len(candidates))
        return candidates[:k]

    relevance = {c.chunk_id: _dot(query_vector, c.values) for c in candidates}

    selected: list[RetrievedChunk] = [max(candidates, key=lambda c: relevance[c.chunk_id])]
    remaining = [c for c in candidates if c.chunk_id != selected[0].chunk_id]

    while remaining and len(selected) < k:
        best, best_score = None, float("-inf")
        for candidate in remaining:
            redundancy = max(_dot(candidate.values, s.values) for s in selected)
            score = lambda_mult * relevance[candidate.chunk_id] - (1 - lambda_mult) * redundancy
            if score > best_score:
                best, best_score = candidate, score

        selected.append(best)
        remaining = [c for c in remaining if c.chunk_id != best.chunk_id]

    return selected


def build_filter(category: str | None) -> dict[str, Any] | None:
    """Turn a category into a Pinecone metadata filter, or ``None`` for no filter.

    The router emits ``None`` when it cannot confidently classify a question. Searching
    unfiltered is the right fallback -- a wrong filter silently hides the answer, which
    is far worse than a slightly noisier candidate set.
    """
    if not category:
        return None
    return {"category": {"$eq": category}}


class OptimizedRetriever:
    """Filtered, over-fetched, MMR-diversified, score-thresholded retrieval."""

    def __init__(
        self,
        *,
        namespace: str | None = None,
        top_k: int | None = None,
        fetch_k: int | None = None,
        mmr_lambda: float | None = None,
        score_threshold: float | None = None,
    ) -> None:
        """Override any parameter for ablation runs; defaults come from settings."""
        self.namespace = namespace or settings.pinecone_namespace
        self.top_k = top_k if top_k is not None else settings.retrieval_top_k
        self.fetch_k = fetch_k if fetch_k is not None else settings.retrieval_fetch_k
        self.mmr_lambda = mmr_lambda if mmr_lambda is not None else settings.retrieval_mmr_lambda
        self.score_threshold = (
            score_threshold if score_threshold is not None else settings.retrieval_score_threshold
        )

    def fetch_candidates(
        self, question: str, *, category: str | None = None
    ) -> tuple[list[float], list[RetrievedChunk]]:
        """Fetch the raw candidate pool from Pinecone, before selection.

        Split out from :meth:`retrieve` because the candidate pool depends only on the
        query, the filter and ``fetch_k`` -- MMR and the score threshold are applied
        afterwards, in memory. The parameter sweep in ``scripts/benchmark_retrieval.py``
        therefore fetches once per question instead of once per configuration, which is
        the difference between one Pinecone round trip and twenty-eight.
        """
        vector = embed_query(question)
        matches = pinecone_query(
            vector,
            top_k=self.fetch_k,
            namespace=self.namespace,
            metadata_filter=build_filter(category),
            include_values=True,
        )
        return vector, [RetrievedChunk.from_match(m) for m in matches]

    def select(self, vector: list[float], candidates: list[RetrievedChunk]) -> list[RetrievedChunk]:
        """Apply the score threshold and MMR to an already-fetched candidate pool."""
        above_threshold = [c for c in candidates if c.score >= self.score_threshold]

        # If thresholding removes everything the question is probably out of scope, but
        # returning nothing here would rob the grader of the chance to say so. Keep the
        # single best candidate and let the LLM judge it.
        if not above_threshold and candidates:
            log.info(
                "all_candidates_below_threshold",
                threshold=self.score_threshold,
                best_score=round(candidates[0].score, 3),
            )
            above_threshold = candidates[:1]

        return maximal_marginal_relevance(
            vector, above_threshold, k=self.top_k, lambda_mult=self.mmr_lambda
        )

    def retrieve(self, question: str, *, category: str | None = None) -> list[RetrievedChunk]:
        """Retrieve chunks for one question: fetch a candidate pool, then select from it."""
        vector, candidates = self.fetch_candidates(question, category=category)
        selected = self.select(vector, candidates)

        log.info(
            "retrieved",
            namespace=self.namespace,
            question=question[:80],
            category_filter=category,
            fetched=len(candidates),
            returned=len(selected),
            top_score=round(selected[0].score, 3) if selected else 0.0,
        )
        return selected


class BaselineRetriever:
    """Plain top-k similarity over the naive chunks. Benchmark comparison arm only."""

    def __init__(self, *, namespace: str | None = None, top_k: int = 5) -> None:
        """Fixed at k=5, unfiltered, no MMR and no threshold -- the tutorial default."""
        self.namespace = namespace or settings.pinecone_baseline_namespace
        self.top_k = top_k

    def retrieve(self, question: str, *, category: str | None = None) -> list[RetrievedChunk]:
        """Retrieve chunks, deliberately ignoring the ``category`` hint."""
        vector = embed_query(question)
        matches = pinecone_query(vector, top_k=self.top_k, namespace=self.namespace)
        return [RetrievedChunk.from_match(m) for m in matches]


def deduplicate(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Drop repeated chunk ids, keeping the highest-scoring occurrence.

    Needed because decomposition runs several sub-queries, and neighbouring sub-queries
    routinely retrieve the same chunk.
    """
    best: dict[str, RetrievedChunk] = {}
    for chunk in chunks:
        existing = best.get(chunk.chunk_id)
        if existing is None or chunk.score > existing.score:
            best[chunk.chunk_id] = chunk
    return sorted(best.values(), key=lambda c: c.score, reverse=True)
