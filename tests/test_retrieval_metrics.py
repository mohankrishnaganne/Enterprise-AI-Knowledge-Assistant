"""Tests for the metric definitions the benchmark's headline number depends on.

If `relative_reduction` or `irrelevant_rate` were subtly wrong, the reported figure would
be wrong in a way no other test would catch — the benchmark would still run and still
print a plausible number. These pin the arithmetic down.
"""

from __future__ import annotations

import pytest

from src.evaluation.golden import GoldenQuestion, split
from src.evaluation.retrieval_metrics import (
    ArmMetrics,
    QuestionResult,
    relative_reduction,
    score_question,
)
from src.retrieval.retriever import RetrievedChunk


def question(**overrides) -> GoldenQuestion:
    """A golden question whose relevance rule is easy to reason about."""
    defaults = dict(
        id="q",
        question="what is the growth rate limit",
        ground_truth="3,000 per minute",
        expected_category="technical",
        expected_sources=("technical/rate_limits.md",),
        answer_phrases=("3,000",),
        answerable=True,
        multi_hop=False,
    )
    return GoldenQuestion(**{**defaults, **overrides})


def chunk(source="technical/rate_limits.md", text="Growth allows 3,000 per minute"):
    """A retrieved chunk."""
    return RetrievedChunk("id", text, source, "technical", "Title", "Section", 0.8)


# ---------------------------------------------------------------------------
# Scoring one question
# ---------------------------------------------------------------------------
def test_scoring_counts_relevant_and_finds_the_first_rank():
    result = score_question(
        question(),
        [
            chunk(text="unrelated preamble"),
            chunk(text="Growth allows 3,000 per minute"),
            chunk(text="also mentions 3,000 requests"),
        ],
    )
    assert result.retrieved == 3
    assert result.relevant == 2
    assert result.first_relevant_rank == 2
    assert result.reciprocal_rank == pytest.approx(0.5)


def test_scoring_a_miss_has_no_rank():
    result = score_question(question(), [chunk(text="nothing useful here")])
    assert result.relevant == 0
    assert result.first_relevant_rank is None
    assert result.reciprocal_rank == 0.0
    assert result.hit is False


def test_wrong_source_is_irrelevant_even_with_the_right_text():
    result = score_question(question(), [chunk(source="business/pricing.md", text="3,000")])
    assert result.relevant == 0


# ---------------------------------------------------------------------------
# The headline metric
# ---------------------------------------------------------------------------
def test_irrelevant_rate_is_the_complement_of_precision():
    result = QuestionResult("q", retrieved=5, relevant=2, first_relevant_rank=1)
    assert result.irrelevant == 3
    assert result.irrelevant_rate == pytest.approx(0.6)
    assert result.precision == pytest.approx(0.4)
    assert result.irrelevant_rate + result.precision == pytest.approx(1.0)


def test_returning_nothing_scores_worst_not_best():
    """Otherwise an arm could win the headline metric by refusing to retrieve."""
    result = QuestionResult("q", retrieved=0, relevant=0, first_relevant_rank=None)
    assert result.irrelevant_rate == 1.0
    assert result.precision == 0.0
    assert result.hit is False


def test_arm_irrelevant_rate_is_macro_averaged():
    """Every question counts equally regardless of how many chunks its arm returned."""
    arm = ArmMetrics("test", "")
    arm.results = [
        QuestionResult("a", retrieved=10, relevant=5, first_relevant_rank=1),  # 0.5
        QuestionResult("b", retrieved=2, relevant=0, first_relevant_rank=None),  # 1.0
    ]
    # Macro: mean(0.5, 1.0) = 0.75. Micro would be 7/12 = 0.583, letting the
    # 10-chunk question dominate.
    assert arm.irrelevant_rate == pytest.approx(0.75)


def test_arm_aggregates_hit_rate_and_mrr():
    arm = ArmMetrics("test", "")
    arm.results = [
        QuestionResult("a", retrieved=5, relevant=1, first_relevant_rank=1),
        QuestionResult("b", retrieved=5, relevant=1, first_relevant_rank=4),
        QuestionResult("c", retrieved=5, relevant=0, first_relevant_rank=None),
    ]
    assert arm.hit_rate == pytest.approx(2 / 3)
    assert arm.mrr == pytest.approx((1.0 + 0.25 + 0.0) / 3)
    assert arm.total_retrieved == 15
    assert arm.total_irrelevant == 13


def test_empty_arm_does_not_divide_by_zero():
    arm = ArmMetrics("empty", "")
    assert arm.irrelevant_rate == 1.0
    assert arm.hit_rate == 0.0
    assert arm.mrr == 0.0


# ---------------------------------------------------------------------------
# The number that goes on the resume
# ---------------------------------------------------------------------------
def test_relative_reduction_is_relative_not_percentage_points():
    """70% -> 50% is a 28.6% relative reduction, not a 20-point one."""
    assert relative_reduction(0.70, 0.50) == pytest.approx(28.571, abs=0.01)


def test_relative_reduction_is_negative_when_things_got_worse():
    assert relative_reduction(0.50, 0.70) < 0


def test_relative_reduction_of_zero_baseline_is_zero_not_infinite():
    assert relative_reduction(0.0, 0.0) == 0.0


def test_relative_reduction_to_zero_is_total():
    assert relative_reduction(0.60, 0.0) == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# The dev/test split guards against tuning overfit
# ---------------------------------------------------------------------------
def test_split_is_disjoint_and_covers_every_answerable_question():
    dev, test = split()
    dev_ids = {q.id for q in dev}
    test_ids = {q.id for q in test}

    assert not (dev_ids & test_ids), "a question must not be both tuned on and reported on"
    assert len(dev) + len(test) == len(dev_ids | test_ids)


def test_split_is_deterministic():
    """A shifting split would make successive benchmark runs incomparable."""
    assert [q.id for q in split()[0]] == [q.id for q in split()[0]]


def test_both_splits_span_every_category():
    """A split concentrated in one category would not generalise."""
    dev, test = split()
    assert {q.expected_category for q in dev} == {"technical", "operational", "business"}
    assert {q.expected_category for q in test} == {"technical", "operational", "business"}
