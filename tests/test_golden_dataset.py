"""The golden dataset must stay consistent with the corpus.

If a golden phrase stops occurring in the corpus (a doc is edited, a file renamed), every
benchmark arm scores zero on that question and the reported numbers become meaningless
without anything failing. This test is the guard against that, and it runs in CI.
"""

from src.evaluation.golden import GoldenQuestion, answerable, load, normalize, validate


def test_dataset_is_consistent_with_the_corpus():
    problems = validate()
    assert not problems, "Golden dataset drifted from the corpus:\n  " + "\n  ".join(problems)


def test_dataset_covers_every_category():
    categories = {q.expected_category for q in answerable()}
    assert categories == {"technical", "operational", "business"}


def test_dataset_includes_multi_hop_and_unanswerable_cases():
    questions = load()
    assert sum(q.multi_hop for q in questions) >= 2, (
        "need multi-hop cases to exercise decomposition"
    )
    assert sum(not q.answerable for q in questions) >= 2, "need unanswerable cases to test fallback"


def test_dataset_includes_a_pdf_sourced_question():
    """Proves the PDF ingestion path is actually evaluated, not just present."""
    sources = {s for q in answerable() for s in q.expected_sources}
    assert any(s.endswith(".pdf") for s in sources)


def test_relevance_rule_requires_both_source_and_phrase():
    question = GoldenQuestion(
        id="t",
        question="q",
        ground_truth="g",
        expected_category="technical",
        expected_sources=("technical/rate_limits.md",),
        answer_phrases=("3,000",),
        answerable=True,
        multi_hop=False,
    )
    assert question.is_relevant("technical/rate_limits.md", "Growth allows 3,000 per minute")
    # Right document, wrong passage.
    assert not question.is_relevant("technical/rate_limits.md", "Sandbox is fixed at 120.")
    # Right passage text, wrong document.
    assert not question.is_relevant("business/pricing.md", "3,000 requests per minute")


def test_relevance_survives_line_wrapping():
    """Phrases straddle newlines in hard-wrapped markdown but not in retrieved chunks."""
    question = GoldenQuestion(
        id="t",
        question="q",
        ground_truth="g",
        expected_category="business",
        expected_sources=("business/competitor_analysis.md",),
        answer_phrases=("not authorised",),
        answerable=True,
        multi_hop=False,
    )
    assert question.is_relevant(
        "business/competitor_analysis.md", "Discounting is not\nauthorised."
    )
    assert normalize("not   authorised\n") == "not authorised"


def test_unanswerable_questions_declare_no_ground_truth_sources():
    for question in load():
        if not question.answerable:
            assert not question.expected_sources
            assert not question.answer_phrases
