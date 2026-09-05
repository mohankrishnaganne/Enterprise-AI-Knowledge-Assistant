"""Node-level tests.

Every LLM call is replaced by a scripted fake, so these run offline and in CI with no
API keys. What is being tested is the control logic around the model -- the loop guard,
the fallback behaviour when a model call fails, evidence selection -- which is where the
bugs in an agent pipeline actually live.
"""

from __future__ import annotations

import pytest

from src.agent import nodes
from src.agent.schemas import (
    DocumentGrade,
    GradingResult,
    RewrittenQuery,
    RouteDecision,
    SubQueries,
)
from src.agent.state import initial_state
from src.config import settings
from src.retrieval.retriever import RetrievedChunk


class FakeStructuredLLM:
    """Returns a queued response, or raises if the response is an exception."""

    def __init__(self, response):
        self.response = response
        self.calls: list = []

    def invoke(self, messages):
        self.calls.append(messages)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class FakeChatLLM:
    """Stands in for a plain (unstructured) chat model."""

    def __init__(self, content: str = "An answer with a citation [1]."):
        self.content = content

    def invoke(self, messages):
        if isinstance(self.content, Exception):
            raise self.content
        return type("Response", (), {"content": self.content})()


class FakeRetriever:
    """Returns a fixed chunk list and records the calls made against it."""

    def __init__(self, chunks: list[RetrievedChunk]):
        self.chunks = chunks
        self.calls: list[tuple[str, str | None]] = []

    def retrieve(self, question, *, category=None):
        self.calls.append((question, category))
        return list(self.chunks)


def make_chunk(chunk_id="c1", source="technical/api_reference.md", score=0.8, text="Body text."):
    """Build a retrieved chunk for tests."""
    return RetrievedChunk(
        chunk_id=chunk_id,
        text=text,
        source=source,
        category=source.split("/")[0],
        doc_title="Doc Title",
        section="Section",
        score=score,
    )


@pytest.fixture(autouse=True)
def _clear_overrides():
    """Ensure no test leaks its fakes into the next one."""
    yield
    nodes._llm_override = None
    nodes._retriever_override = None


def patch_llm(response):
    """Route every structured LLM call in the nodes to a fake."""
    fake = FakeStructuredLLM(response)
    nodes._llm_override = lambda schema, tier: fake
    return fake


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------
def test_route_query_sets_filter_and_intent():
    patch_llm(
        RouteDecision(
            intent="knowledge",
            category="operational",
            needs_decomposition=False,
            reason="asks about internal policy",
        )
    )
    update = nodes.route_query(initial_state("How much PTO do I get?"))

    assert update["intent"] == "knowledge"
    assert update["category_filter"] == "operational"
    # A focused question is pre-seeded so decompose_query can skip its LLM call.
    assert update["subqueries"] == ["How much PTO do I get?"]


def test_route_query_unknown_category_means_no_filter():
    """An uncertain router must not filter -- a wrong filter hides the answer entirely."""
    patch_llm(
        RouteDecision(
            intent="knowledge", category="unknown", needs_decomposition=False, reason="ambiguous"
        )
    )
    assert nodes.route_query(initial_state("Tell me about limits"))["category_filter"] is None


def test_route_query_failure_falls_back_to_unfiltered_knowledge_search():
    patch_llm(RuntimeError("groq exploded"))
    update = nodes.route_query(initial_state("anything"))

    assert update["intent"] == "knowledge"
    assert update["category_filter"] is None
    assert "router failed" in update["trace"][0]["detail"]


def test_decompose_is_skipped_when_router_says_focused():
    fake = patch_llm(SubQueries(subqueries=["should not be called"]))
    state = initial_state("q")
    state["subqueries"] = ["q"]

    nodes.decompose_query(state)
    assert fake.calls == [], "decomposition should not call the LLM for a focused question"


def test_decompose_respects_the_subquery_cap():
    patch_llm(SubQueries(subqueries=["a", "b", "c"]))
    state = initial_state("compound question")
    state["subqueries"] = []

    update = nodes.decompose_query(state)
    assert len(update["subqueries"]) <= settings.max_subqueries


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
def test_retrieve_uses_subqueries_and_deduplicates():
    shared = make_chunk("dup", score=0.9)
    nodes._retriever_override = FakeRetriever([shared, make_chunk("other", score=0.5)])

    state = initial_state("q")
    state["subqueries"] = ["sub one", "sub two"]

    update = nodes.retrieve(state)
    ids = [c.chunk_id for c in update["documents"]]

    assert nodes._retriever_override.calls == [("sub one", None), ("sub two", None)]
    assert ids == sorted(set(ids), key=ids.index), "duplicates across sub-queries must be merged"
    assert len(ids) == 2


def test_retrieve_after_rewrite_uses_the_rewritten_query_only():
    """The retry must search something new, not replay the original plan."""
    nodes._retriever_override = FakeRetriever([make_chunk()])

    state = initial_state("original question")
    state["subqueries"] = ["stale sub-query"]
    state["search_query"] = "rewritten query"
    state["rewrites"] = 1

    nodes.retrieve(state)
    assert nodes._retriever_override.calls == [("rewritten query", None)]


def test_retrieve_passes_the_category_filter_through():
    nodes._retriever_override = FakeRetriever([make_chunk()])
    state = initial_state("q")
    state["category_filter"] = "business"

    nodes.retrieve(state)
    assert nodes._retriever_override.calls[0][1] == "business"


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------
def test_grade_documents_keeps_only_relevant_chunks():
    patch_llm(
        GradingResult(
            grades=[
                DocumentGrade(index=1, relevant=True, reason="contains the figure"),
                DocumentGrade(index=2, relevant=False, reason="different topic"),
            ]
        )
    )
    state = initial_state("q")
    state["documents"] = [make_chunk("a"), make_chunk("b")]

    update = nodes.grade_documents(state)

    assert [c.chunk_id for c in update["relevant_documents"]] == ["a"]
    assert state["documents"][0].is_relevant is True
    assert state["documents"][1].is_relevant is False


def test_grade_documents_keeps_everything_when_the_judge_fails():
    """Dropping all evidence on a grader outage would fabricate a 'no evidence' answer."""
    patch_llm(RuntimeError("judge unavailable"))
    state = initial_state("q")
    state["documents"] = [make_chunk("a"), make_chunk("b")]

    update = nodes.grade_documents(state)
    assert len(update["relevant_documents"]) == 2


def test_grade_documents_handles_an_empty_retrieval():
    update = nodes.grade_documents(initial_state("q"))
    assert update["relevant_documents"] == []


# ---------------------------------------------------------------------------
# Source validation
# ---------------------------------------------------------------------------
def test_validate_sources_prefers_distinct_documents():
    """Citation spread matters on multi-hop questions, so diversify before truncating."""
    state = initial_state("q")
    state["relevant_documents"] = [
        make_chunk("a1", "technical/api_reference.md", score=0.95),
        make_chunk("a2", "technical/api_reference.md", score=0.94),
        make_chunk("a3", "technical/api_reference.md", score=0.93),
        make_chunk("b1", "business/pricing.md", score=0.60),
    ]

    selected = nodes.validate_sources(state)["relevant_documents"]
    assert "business/pricing.md" in {c.source for c in selected}


def test_validate_sources_caps_the_evidence_set():
    state = initial_state("q")
    state["relevant_documents"] = [
        make_chunk(f"c{i}", f"technical/doc{i}.md", score=0.9 - i / 100) for i in range(10)
    ]
    assert len(nodes.validate_sources(state)["relevant_documents"]) == 4


# ---------------------------------------------------------------------------
# Self-correction
# ---------------------------------------------------------------------------
def test_rewrite_increments_the_loop_counter_and_clears_subqueries():
    patch_llm(RewrittenQuery(query="pto policy accrual carryover", strategy="policy terminology"))
    state = initial_state("how much holiday")
    state["subqueries"] = ["how much holiday"]

    update = nodes.rewrite_query(state)

    assert update["rewrites"] == 1
    assert update["search_query"] == "pto policy accrual carryover"
    assert update["subqueries"] == [], "stale sub-queries would undo the rewrite"


def test_rewrite_failure_falls_back_to_the_original_question():
    patch_llm(RuntimeError("no"))
    state = initial_state("original")
    state["search_query"] = "failed query"

    update = nodes.rewrite_query(state)
    assert update["search_query"] == "original"
    assert update["rewrites"] == 1


def test_decide_after_grading_generates_when_evidence_exists():
    state = initial_state("q")
    state["relevant_documents"] = [make_chunk()]
    assert nodes.decide_after_grading(state) == "generate"


def test_decide_after_grading_retries_within_budget():
    state = initial_state("q")
    state["relevant_documents"] = []
    state["rewrites"] = settings.max_query_rewrites - 1
    assert nodes.decide_after_grading(state) == "rewrite"


def test_decide_after_grading_gives_up_at_the_budget():
    """The loop guard: without this the retrieve/grade/rewrite cycle never terminates."""
    state = initial_state("q")
    state["relevant_documents"] = []
    state["rewrites"] = settings.max_query_rewrites
    assert nodes.decide_after_grading(state) == "fallback"


def test_decide_after_routing_splits_knowledge_from_chitchat():
    for intent, expected in [
        ("knowledge", "knowledge"),
        ("chitchat", "direct"),
        ("out_of_scope", "direct"),
    ]:
        state = initial_state("q")
        state["intent"] = intent
        assert nodes.decide_after_routing(state) == expected


# ---------------------------------------------------------------------------
# Answering
# ---------------------------------------------------------------------------
def test_generate_builds_numbered_citations(monkeypatch):
    monkeypatch.setattr(nodes, "get_llm", lambda tier="fast": FakeChatLLM("Answer [1][2]."))
    state = initial_state("q")
    state["relevant_documents"] = [
        make_chunk("a", "technical/api_reference.md"),
        make_chunk("b", "business/pricing.md"),
    ]

    update = nodes.generate(state)

    assert [c["n"] for c in update["citations"]] == [1, 2]
    assert update["citations"][0]["source"] == "technical/api_reference.md"
    assert update["insufficient_evidence"] is False


def test_generate_normalizes_fullwidth_citation_brackets(monkeypatch):
    """gpt-oss intermittently emits CJK brackets, which break citation linking."""
    monkeypatch.setattr(nodes, "get_llm", lambda tier="fast": FakeChatLLM("Answer 【1】 here."))
    state = initial_state("q")
    state["relevant_documents"] = [make_chunk()]

    assert nodes.generate(state)["answer"] == "Answer [1] here."


def test_normalize_citation_markers_is_a_noop_on_ascii():
    assert nodes.normalize_citation_markers("Answer [1][2].") == "Answer [1][2]."


def test_fallback_declines_and_flags_insufficient_evidence():
    state = initial_state("q")
    state["rewrites"] = 2

    update = nodes.fallback(state)

    assert update["insufficient_evidence"] is True
    assert update["citations"] == []
    assert "3 times" in update["answer"], "should report total attempts, not rewrites"


# ---------------------------------------------------------------------------
# Transient Groq schema failures
# ---------------------------------------------------------------------------
def test_transient_schema_failure_is_recognised():
    from src.agent.llm import is_transient_schema_failure

    groq_400 = Exception(
        "Error code: 400 - {'error': {'message': \"Failed to validate JSON.\", "
        "'code': 'json_validate_failed', 'failed_generation': ''}}"
    )
    assert is_transient_schema_failure(groq_400)


def test_genuine_errors_are_not_treated_as_transient():
    """Retrying a real failure would just triple the latency before failing anyway."""
    from src.agent.llm import is_transient_schema_failure

    assert not is_transient_schema_failure(Exception("Error code: 401 - invalid api key"))
    assert not is_transient_schema_failure(Exception("Error code: 429 - rate limited"))
    assert not is_transient_schema_failure(ValueError("something else entirely"))


def test_structured_model_retries_a_transient_failure_then_succeeds():
    from src.agent.llm import _RetryingStructuredModel

    class Flaky:
        def __init__(self):
            self.calls = 0

        def invoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                raise Exception("Error code: 400 - {'code': 'json_validate_failed'}")
            return "recovered"

    flaky = Flaky()
    assert _RetryingStructuredModel(flaky).invoke([]) == "recovered"
    assert flaky.calls == 2


def test_structured_model_does_not_retry_a_real_error():
    from src.agent.llm import _RetryingStructuredModel

    class AlwaysUnauthorized:
        def __init__(self):
            self.calls = 0

        def invoke(self, messages):
            self.calls += 1
            raise Exception("Error code: 401 - invalid api key")

    model = AlwaysUnauthorized()
    with pytest.raises(Exception, match="401"):
        _RetryingStructuredModel(model).invoke([])
    assert model.calls == 1, "a 401 must fail immediately, not after three attempts"
