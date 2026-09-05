"""Graph-level tests: topology, and the paths taken end to end.

These compile and run the real LangGraph workflow with fake models and a fake retriever,
so they verify the wiring -- including the retry cycle -- rather than any node in
isolation. They run offline and need no API keys.
"""

from __future__ import annotations

import pytest

from src.agent import nodes
from src.agent.graph import _recursion_limit, build_graph
from src.agent.schemas import DocumentGrade, GradingResult, RewrittenQuery, RouteDecision
from src.agent.state import initial_state, trace_path
from src.config import settings
from tests.test_agent_nodes import FakeChatLLM, FakeRetriever, make_chunk


class ScriptedLLM:
    """Dispatches each structured call to a canned response keyed by output schema."""

    def __init__(self, by_schema: dict):
        self.by_schema = by_schema
        self.schema_calls: list[str] = []

    def __call__(self, schema, tier):
        self.schema_calls.append(schema.__name__)
        response = self.by_schema[schema.__name__]
        outer = self

        class Bound:
            def invoke(self, messages):
                if callable(response) and not isinstance(response, type):
                    return response(len(outer.schema_calls))
                return response

        return Bound()


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    nodes._llm_override = None
    nodes._retriever_override = None


def run(question: str):
    """Compile and invoke the graph, returning the final state."""
    graph = build_graph().compile()
    return graph.invoke(initial_state(question), config={"recursion_limit": _recursion_limit()})


# ---------------------------------------------------------------------------
# Topology
# ---------------------------------------------------------------------------
def test_graph_contains_every_expected_node():
    compiled = build_graph().compile()
    names = set(compiled.get_graph().nodes)

    assert {
        "route_query",
        "decompose_query",
        "retrieve",
        "grade_documents",
        "validate_sources",
        "generate",
        "rewrite_query",
        "direct_answer",
        "fallback",
    } <= names


def test_graph_has_a_cycle_back_into_retrieval():
    """The retrieve -> grade -> rewrite -> retrieve cycle is what makes this agentic."""
    compiled = build_graph().compile()
    edges = {(e.source, e.target) for e in compiled.get_graph().edges}

    assert ("rewrite_query", "retrieve") in edges
    assert ("retrieve", "grade_documents") in edges


def test_recursion_limit_allows_every_permitted_retry():
    # Each retry costs retrieve + grade + rewrite; the limit must exceed the longest
    # legal path or a legitimate second attempt would be aborted as runaway recursion.
    longest_legal_path = 2 + 3 * settings.max_query_rewrites + 4
    assert _recursion_limit() > longest_legal_path


# ---------------------------------------------------------------------------
# End-to-end paths
# ---------------------------------------------------------------------------
def test_chitchat_never_touches_retrieval(monkeypatch):
    nodes._llm_override = ScriptedLLM(
        {
            "RouteDecision": RouteDecision(
                intent="chitchat", category="unknown", needs_decomposition=False, reason="greeting"
            )
        }
    )
    nodes._retriever_override = FakeRetriever([make_chunk()])
    monkeypatch.setattr(nodes, "get_llm", lambda tier="fast": FakeChatLLM("Hello!"))

    final = run("hi there")

    assert trace_path(final) == "route_query -> direct_answer"
    assert nodes._retriever_override.calls == [], "chitchat must not hit the vector store"
    assert final["citations"] == []


def test_out_of_scope_is_answered_directly(monkeypatch):
    nodes._llm_override = ScriptedLLM(
        {
            "RouteDecision": RouteDecision(
                intent="out_of_scope",
                category="unknown",
                needs_decomposition=False,
                reason="general knowledge",
            )
        }
    )
    nodes._retriever_override = FakeRetriever([make_chunk()])
    monkeypatch.setattr(nodes, "get_llm", lambda tier="fast": FakeChatLLM("Out of scope."))

    assert trace_path(run("who won the world cup")) == "route_query -> direct_answer"


def test_happy_path_answers_with_citations(monkeypatch):
    nodes._llm_override = ScriptedLLM(
        {
            "RouteDecision": RouteDecision(
                intent="knowledge",
                category="technical",
                needs_decomposition=False,
                reason="api question",
            ),
            "GradingResult": GradingResult(
                grades=[DocumentGrade(index=1, relevant=True, reason="has the answer")]
            ),
        }
    )
    nodes._retriever_override = FakeRetriever([make_chunk("a")])
    monkeypatch.setattr(nodes, "get_llm", lambda tier="fast": FakeChatLLM("The limit is 3000 [1]."))

    final = run("what is the rate limit")

    assert trace_path(final) == (
        "route_query -> decompose_query -> retrieve -> grade_documents "
        "-> validate_sources -> generate"
    )
    assert final["rewrites"] == 0
    assert len(final["citations"]) == 1
    assert final["insufficient_evidence"] is False


def test_irrelevant_results_trigger_a_rewrite_then_succeed(monkeypatch):
    """The self-correction path: bad evidence, new query, good evidence, answer."""
    grading_calls = {"n": 0}

    def grade(_call_index):
        grading_calls["n"] += 1
        # Fail the first grading pass, pass the second.
        relevant = grading_calls["n"] > 1
        return GradingResult(grades=[DocumentGrade(index=1, relevant=relevant, reason="verdict")])

    nodes._llm_override = ScriptedLLM(
        {
            "RouteDecision": RouteDecision(
                intent="knowledge",
                category="operational",
                needs_decomposition=False,
                reason="policy",
            ),
            "GradingResult": grade,
            "RewrittenQuery": RewrittenQuery(query="pto accrual", strategy="policy terms"),
        }
    )
    nodes._retriever_override = FakeRetriever([make_chunk("a")])
    monkeypatch.setattr(nodes, "get_llm", lambda tier="fast": FakeChatLLM("25 days [1]."))

    final = run("how much holiday")
    path = trace_path(final)

    assert "rewrite_query" in path
    assert path.endswith("generate")
    assert final["rewrites"] == 1
    # The retry must have searched the rewritten query, not the original.
    assert nodes._retriever_override.calls[-1][0] == "pto accrual"


def test_persistently_irrelevant_results_end_in_an_honest_refusal(monkeypatch):
    nodes._llm_override = ScriptedLLM(
        {
            "RouteDecision": RouteDecision(
                intent="knowledge", category="business", needs_decomposition=False, reason="biz"
            ),
            "GradingResult": GradingResult(
                grades=[DocumentGrade(index=1, relevant=False, reason="unrelated")]
            ),
            "RewrittenQuery": RewrittenQuery(query="another attempt", strategy="broadened"),
        }
    )
    nodes._retriever_override = FakeRetriever([make_chunk("a")])
    monkeypatch.setattr(nodes, "get_llm", lambda tier="fast": FakeChatLLM("should never run"))

    final = run("what is our crypto payment policy")
    path = trace_path(final)

    assert path.endswith("fallback")
    assert "generate" not in path, "must not answer without evidence"
    assert final["insufficient_evidence"] is True
    assert final["citations"] == []
    # Exactly the permitted number of rewrites, no more.
    assert final["rewrites"] == settings.max_query_rewrites
    assert path.count("rewrite_query") == settings.max_query_rewrites


def test_the_loop_terminates_rather_than_hitting_the_recursion_limit(monkeypatch):
    """A guard that fails would surface as a GraphRecursionError, not a fallback answer."""
    nodes._llm_override = ScriptedLLM(
        {
            "RouteDecision": RouteDecision(
                intent="knowledge", category="unknown", needs_decomposition=False, reason="x"
            ),
            "GradingResult": GradingResult(grades=[]),
            "RewrittenQuery": RewrittenQuery(query="again", strategy="again"),
        }
    )
    nodes._retriever_override = FakeRetriever([make_chunk("a")])
    monkeypatch.setattr(nodes, "get_llm", lambda tier="fast": FakeChatLLM("unused"))

    final = run("something never in the corpus")
    assert final["answer"], "graph must terminate with an answer, not raise"
    assert final["insufficient_evidence"] is True
