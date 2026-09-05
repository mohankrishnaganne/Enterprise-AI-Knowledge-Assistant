"""Golden dataset loading, validation and the relevance rule.

The relevance rule defined here is the definition behind every number the retrieval
benchmark reports, so it is deliberately in one place and deliberately simple:

    A retrieved chunk is RELEVANT iff its ``source`` is one of the question's
    ``expected_sources`` AND its text contains at least one of the question's
    ``answer_phrases`` (case-insensitively).

It is keyed on source plus content rather than on ``chunk_id`` because the optimized and
baseline arms cut the documents at different boundaries, so their chunk ids are not
comparable. Anything retrieved that fails the rule is counted as an irrelevant result.

:func:`validate` is not optional book-keeping. If a golden phrase does not occur in the
corpus, every arm scores zero on that question and the benchmark silently measures
nothing, so validation runs before any scoring.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.config import GOLDEN_DATASET_PATH
from src.logging_conf import get_logger

log = get_logger(__name__)

_WHITESPACE_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Lowercase and collapse whitespace before phrase matching.

    Source markdown is hard-wrapped, so a phrase like "not authorised" can straddle a
    newline in the file and a space in a retrieved chunk. Matching on raw text would make
    the relevance rule depend on line wrapping, which has nothing to do with retrieval
    quality.
    """
    return _WHITESPACE_RE.sub(" ", text).lower().strip()


@dataclass(frozen=True)
class GoldenQuestion:
    """One evaluation question with its ground truth."""

    id: str
    question: str
    ground_truth: str
    expected_category: str
    expected_sources: tuple[str, ...]
    answer_phrases: tuple[str, ...]
    answerable: bool
    multi_hop: bool

    def is_relevant(self, source: str, text: str) -> bool:
        """Apply the relevance rule to one retrieved chunk."""
        if source not in self.expected_sources:
            return False
        haystack = normalize(text)
        return any(normalize(phrase) in haystack for phrase in self.answer_phrases)


class GoldenDatasetError(RuntimeError):
    """Raised when the golden dataset is missing, malformed, or inconsistent."""


def load(path: Path = GOLDEN_DATASET_PATH) -> list[GoldenQuestion]:
    """Load every question from the golden dataset file."""
    if not path.is_file():
        raise GoldenDatasetError(f"Golden dataset not found at {path}.")

    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    raw = payload.get("questions")
    if not raw:
        raise GoldenDatasetError(f"No `questions` array in {path}.")

    questions = [
        GoldenQuestion(
            id=item["id"],
            question=item["question"],
            ground_truth=item["ground_truth"],
            expected_category=item["expected_category"],
            expected_sources=tuple(item["expected_sources"]),
            answer_phrases=tuple(item["answer_phrases"]),
            answerable=bool(item["answerable"]),
            multi_hop=bool(item["multi_hop"]),
        )
        for item in raw
    ]

    ids = [q.id for q in questions]
    if len(set(ids)) != len(ids):
        raise GoldenDatasetError("Duplicate question ids in the golden dataset.")

    return questions


def answerable(questions: list[GoldenQuestion] | None = None) -> list[GoldenQuestion]:
    """Return only the questions the corpus can actually answer."""
    return [q for q in (questions or load()) if q.answerable]


def validate(questions: list[GoldenQuestion] | None = None) -> list[str]:
    """Check the golden set against the corpus on disk.

    Verifies that every expected source file exists, that every answer phrase actually
    occurs in the document that is supposed to contain it, and that answerable questions
    declare at least one source and phrase.

    Returns:
        A list of human-readable problems. Empty means the dataset is sound.
    """
    from src.ingestion.loaders import load_corpus

    questions = questions or load()
    corpus = {doc.metadata["source"]: doc.page_content for doc in load_corpus()}
    problems: list[str] = []

    for question in questions:
        if not question.answerable:
            if question.expected_sources or question.answer_phrases:
                problems.append(
                    f"{question.id}: marked unanswerable but declares sources or phrases."
                )
            continue

        if not question.expected_sources:
            problems.append(f"{question.id}: answerable but declares no expected_sources.")
        if not question.answer_phrases:
            problems.append(f"{question.id}: answerable but declares no answer_phrases.")

        for source in question.expected_sources:
            if source not in corpus:
                problems.append(f"{question.id}: expected source {source!r} is not in the corpus.")

        # Every phrase must appear in at least one of the expected sources, otherwise no
        # retrieved chunk can ever satisfy the relevance rule.
        haystack = normalize("\n".join(corpus[s] for s in question.expected_sources if s in corpus))
        for phrase in question.answer_phrases:
            if normalize(phrase) not in haystack:
                problems.append(
                    f"{question.id}: phrase {phrase!r} does not occur in "
                    f"{list(question.expected_sources)}."
                )

    log.info(
        "golden_dataset_validated",
        questions=len(questions),
        answerable=sum(1 for q in questions if q.answerable),
        multi_hop=sum(1 for q in questions if q.multi_hop),
        problems=len(problems),
    )
    return problems


def split(
    questions: list[GoldenQuestion] | None = None,
) -> tuple[list[GoldenQuestion], list[GoldenQuestion]]:
    """Split the answerable questions into a tuning set and a held-out test set.

    Retrieval parameters (the score threshold in particular) have to be chosen against
    *something*. Choosing them against the same questions the benchmark then reports on
    is overfitting, and with only 15 questions it would overfit badly. So the tuning
    happens on ``dev`` and the headline number is measured on ``test``.

    The split alternates by position rather than randomising, so it is deterministic
    across runs and keeps both halves spread across the three categories -- the questions
    are ordered technical, then operational, then business.

    Returns:
        ``(dev, test)``. With 15 answerable questions this is 8 and 7.
    """
    items = answerable(questions)
    dev = [q for i, q in enumerate(items) if i % 2 == 0]
    test = [q for i, q in enumerate(items) if i % 2 == 1]
    return dev, test
