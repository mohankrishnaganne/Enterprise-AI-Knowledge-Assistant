"""Retrieval metrics.

The headline metric is the **irrelevant-result rate**: of the chunks a retriever returns,
what fraction fail the golden set's relevance rule. It is the direct measure of "how much
noise does this retriever put in front of the generator", and reducing it is the point of
every optimization in :mod:`src.retrieval.retriever`.

Two honesty notes that belong with the numbers rather than buried in a report:

1. **Recall here is hit rate, not true recall.** True recall needs every relevant chunk
   in the corpus labelled, which this golden set does not do -- it labels the passages
   that contain the answer, not exhaustively every passage that mentions it. So
   :func:`hit_rate` reports "did at least one relevant chunk come back", which is what
   actually determines whether the question is answerable, and is not called recall.

2. **Arms retrieve different numbers of chunks.** The optimized retriever can return
   fewer than ``k`` because of the score threshold. A rate is the right comparison for
   that; a raw count would reward returning more.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean

from src.evaluation.golden import GoldenQuestion
from src.retrieval.retriever import RetrievedChunk


@dataclass
class QuestionResult:
    """Per-question retrieval outcome for one arm."""

    question_id: str
    retrieved: int
    relevant: int
    first_relevant_rank: int | None
    sources: list[str] = field(default_factory=list)

    @property
    def irrelevant(self) -> int:
        """Number of returned chunks that failed the relevance rule."""
        return self.retrieved - self.relevant

    @property
    def irrelevant_rate(self) -> float:
        """Fraction of returned chunks that were irrelevant.

        A retriever that returns nothing has no irrelevant results, but it has also
        failed. That case is counted as 1.0 rather than 0.0 so an arm cannot score
        perfectly by refusing to answer.
        """
        if self.retrieved == 0:
            return 1.0
        return self.irrelevant / self.retrieved

    @property
    def precision(self) -> float:
        """Fraction of returned chunks that were relevant."""
        return 0.0 if self.retrieved == 0 else self.relevant / self.retrieved

    @property
    def reciprocal_rank(self) -> float:
        """1 / rank of the first relevant chunk, or 0 if none was returned."""
        return 0.0 if self.first_relevant_rank is None else 1.0 / self.first_relevant_rank

    @property
    def hit(self) -> bool:
        """Whether at least one relevant chunk was returned."""
        return self.relevant > 0


@dataclass
class ArmMetrics:
    """Aggregated metrics for one retrieval configuration."""

    name: str
    description: str
    results: list[QuestionResult] = field(default_factory=list)

    @property
    def irrelevant_rate(self) -> float:
        """Mean per-question irrelevant rate.

        Macro-averaged (mean of per-question rates), not micro-averaged (total
        irrelevant / total retrieved), so every question counts equally regardless of how
        many chunks its arm happened to return.
        """
        return mean(r.irrelevant_rate for r in self.results) if self.results else 1.0

    @property
    def precision(self) -> float:
        """Mean per-question precision."""
        return mean(r.precision for r in self.results) if self.results else 0.0

    @property
    def mrr(self) -> float:
        """Mean reciprocal rank of the first relevant chunk."""
        return mean(r.reciprocal_rank for r in self.results) if self.results else 0.0

    @property
    def hit_rate(self) -> float:
        """Fraction of questions where at least one relevant chunk was retrieved."""
        return mean(1.0 if r.hit else 0.0 for r in self.results) if self.results else 0.0

    @property
    def mean_retrieved(self) -> float:
        """Mean number of chunks returned per question."""
        return mean(r.retrieved for r in self.results) if self.results else 0.0

    @property
    def total_retrieved(self) -> int:
        """Total chunks returned across all questions."""
        return sum(r.retrieved for r in self.results)

    @property
    def total_irrelevant(self) -> int:
        """Total irrelevant chunks returned across all questions."""
        return sum(r.irrelevant for r in self.results)


def score_question(question: GoldenQuestion, chunks: list[RetrievedChunk]) -> QuestionResult:
    """Apply the golden relevance rule to one question's retrieved chunks."""
    relevant = 0
    first_relevant_rank: int | None = None

    for rank, chunk in enumerate(chunks, start=1):
        if question.is_relevant(chunk.source, chunk.text):
            relevant += 1
            if first_relevant_rank is None:
                first_relevant_rank = rank

    return QuestionResult(
        question_id=question.id,
        retrieved=len(chunks),
        relevant=relevant,
        first_relevant_rank=first_relevant_rank,
        sources=[c.source for c in chunks],
    )


def relative_reduction(baseline: float, optimized: float) -> float:
    """Percentage reduction from ``baseline`` to ``optimized``.

    This is the number that goes on the resume, so it is defined in exactly one place:
    the *relative* reduction, ``(baseline - optimized) / baseline * 100``. Reporting the
    absolute difference in percentage points instead would be a larger-sounding but
    different claim, and the two are routinely confused.
    """
    if baseline == 0:
        return 0.0
    return (baseline - optimized) / baseline * 100.0
