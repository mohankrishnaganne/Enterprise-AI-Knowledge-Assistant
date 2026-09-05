"""Graph nodes.

Each node takes the state and returns a partial update. They are plain functions with no
LangGraph-specific machinery, which keeps them unit-testable in isolation: every test in
``tests/test_agent_nodes.py`` calls these directly with a fake LLM.

Every node appends to ``trace``, so the path through the graph -- including a retry loop
-- is recoverable after the fact and renderable in the UI.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from src.agent import prompts
from src.agent.llm import get_llm, structured
from src.agent.schemas import GradingResult, RewrittenQuery, RouteDecision, SubQueries
from src.agent.state import AgentState, TraceEntry
from src.config import settings
from src.logging_conf import get_logger
from src.retrieval.retriever import OptimizedRetriever, RetrievedChunk, deduplicate

log = get_logger(__name__)

# Injected in tests so nodes can be exercised without network access. Production leaves
# these as None and the real factories in `src.agent.llm` are used.
_llm_override: Callable[..., Any] | None = None
_retriever_override: Any | None = None


def _structured(schema: type, tier: str = "fast"):
    """Return a schema-bound model, honouring a test override."""
    if _llm_override is not None:
        return _llm_override(schema, tier)
    return structured(schema, tier)


def _retriever() -> Any:
    """Return the retriever, honouring a test override."""
    return _retriever_override if _retriever_override is not None else OptimizedRetriever()


def _trace(node: str, detail: str, started: float) -> list[TraceEntry]:
    """Build the single-entry trace list a node returns."""
    return [
        {
            "node": node,
            "detail": detail,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
    ]


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------
def route_query(state: AgentState) -> dict[str, Any]:
    """Classify intent and choose a retrieval filter.

    This is the tool-based routing step: it decides whether the knowledge base is used at
    all, which slice of it to search, and whether the question needs decomposing.
    """
    started = time.perf_counter()
    question = state["question"]

    try:
        decision: RouteDecision = _structured(RouteDecision).invoke(
            [
                ("system", prompts.ROUTER_SYSTEM),
                ("human", prompts.ROUTER_USER.format(question=question)),
            ]
        )
    except Exception as exc:  # noqa: BLE001
        # A routing failure must not sink the request. Searching unfiltered is the safe
        # default: it is slower and noisier, but it cannot hide the answer.
        log.warning("routing_failed_defaulting_to_knowledge", error=str(exc))
        return {
            "intent": "knowledge",
            "category_filter": None,
            "routing_reason": f"router error, defaulted to unfiltered search ({exc})",
            **{"trace": _trace("route_query", "router failed; unfiltered fallback", started)},
        }

    log.info(
        "routed",
        intent=decision.intent,
        category=decision.category,
        decompose=decision.needs_decomposition,
    )

    return {
        "intent": decision.intent,
        "category_filter": decision.category_filter,
        "routing_reason": decision.reason,
        # Stashed so `decompose_query` knows whether to bother with an LLM call.
        "subqueries": [] if decision.needs_decomposition else [question],
        "trace": _trace(
            "route_query",
            f"intent={decision.intent}, category={decision.category}",
            started,
        ),
    }


def decompose_query(state: AgentState) -> dict[str, Any]:
    """Split a compound question into independently searchable sub-queries.

    Skipped without an LLM call when the router already judged the question focused --
    most questions are, and this keeps the common path at one fewer request.
    """
    started = time.perf_counter()
    question = state["question"]

    if state.get("subqueries"):
        return {
            "trace": _trace("decompose_query", "not needed; single focused query", started),
        }

    try:
        result: SubQueries = _structured(SubQueries).invoke(
            [
                ("system", prompts.DECOMPOSE_SYSTEM),
                ("human", prompts.DECOMPOSE_USER.format(question=question)),
            ]
        )
        subqueries = [q.strip() for q in result.subqueries if q.strip()][: settings.max_subqueries]
    except Exception as exc:  # noqa: BLE001
        log.warning("decomposition_failed", error=str(exc))
        subqueries = [question]

    if not subqueries:
        subqueries = [question]

    log.info("decomposed", count=len(subqueries), subqueries=subqueries)
    return {
        "subqueries": subqueries,
        "trace": _trace("decompose_query", f"{len(subqueries)} sub-queries", started),
    }


# ---------------------------------------------------------------------------
# Retrieval and grading
# ---------------------------------------------------------------------------
def retrieve(state: AgentState) -> dict[str, Any]:
    """Fetch candidate chunks for every sub-query and merge them.

    On a retry, ``search_query`` has been replaced by ``rewrite_query`` and the
    sub-queries are discarded, so the second attempt genuinely searches for something
    different rather than repeating the first.
    """
    started = time.perf_counter()
    retriever = _retriever()
    category = state.get("category_filter")

    if state.get("rewrites", 0) > 0:
        queries = [state["search_query"]]
    else:
        queries = state.get("subqueries") or [state["search_query"]]

    collected: list[RetrievedChunk] = []
    for query in queries:
        collected.extend(retriever.retrieve(query, category=category))

    documents = deduplicate(collected)

    # Several sub-queries can together exceed the per-query budget; cap the merged set so
    # the grading prompt stays a predictable size.
    cap = settings.retrieval_top_k * 2 if len(queries) > 1 else settings.retrieval_top_k
    documents = documents[:cap]

    detail = (
        f"{len(documents)} chunks from {len(queries)} quer{'y' if len(queries) == 1 else 'ies'}"
    )
    if category:
        detail += f", filtered to {category}"

    return {
        "documents": documents,
        "trace": _trace("retrieve", detail, started),
    }


def grade_documents(state: AgentState) -> dict[str, Any]:
    """Judge each retrieved chunk for relevance with an LLM.

    One batched call for the whole set rather than one per chunk: with six chunks that is
    1 request instead of 6 against the Groq per-minute limit, and it lets the model
    compare candidates against each other rather than in isolation.
    """
    started = time.perf_counter()
    documents = state.get("documents", [])

    if not documents:
        return {
            "relevant_documents": [],
            "trace": _trace("grade_documents", "nothing retrieved to grade", started),
        }

    try:
        result: GradingResult = _structured(GradingResult).invoke(
            [
                ("system", prompts.GRADER_SYSTEM),
                (
                    "human",
                    prompts.GRADER_USER.format(
                        question=state["question"],
                        documents=prompts.format_documents_for_grading(documents),
                        count=len(documents),
                    ),
                ),
            ]
        )
        grades = {g.index: g for g in result.grades}
    except Exception as exc:  # noqa: BLE001
        # If the judge fails, keeping the retrieved documents is safer than discarding
        # them: the generator is still constrained to cite what it is given, whereas
        # dropping everything would produce a false "no evidence" answer.
        log.warning("grading_failed_keeping_all", error=str(exc))
        for doc in documents:
            doc.is_relevant, doc.grade_reason = True, "grader unavailable; not filtered"
        return {
            "relevant_documents": documents,
            "trace": _trace(
                "grade_documents", f"grader failed; kept all {len(documents)}", started
            ),
        }

    relevant: list[RetrievedChunk] = []
    for i, doc in enumerate(documents, start=1):
        grade = grades.get(i)
        doc.is_relevant = bool(grade and grade.relevant)
        doc.grade_reason = grade.reason if grade else "not graded"
        if doc.is_relevant:
            relevant.append(doc)

    log.info("graded", total=len(documents), relevant=len(relevant))
    return {
        "relevant_documents": relevant,
        "trace": _trace("grade_documents", f"{len(relevant)}/{len(documents)} relevant", started),
    }


def validate_sources(state: AgentState) -> dict[str, Any]:
    """Order and cap the evidence that reaches the generator.

    Relevance is not the same as usefulness. Passing every relevant chunk dilutes the
    prompt, so this keeps the highest-scoring few and prefers distinct source documents,
    which produces better citation spread on multi-hop questions.
    """
    started = time.perf_counter()
    relevant = sorted(state.get("relevant_documents", []), key=lambda d: d.score, reverse=True)

    # One pass preferring unseen sources, then a second to fill remaining slots.
    limit = 4
    seen_sources: set[str] = set()
    selected: list[RetrievedChunk] = []

    for doc in relevant:
        if doc.source not in seen_sources and len(selected) < limit:
            selected.append(doc)
            seen_sources.add(doc.source)

    for doc in relevant:
        if doc not in selected and len(selected) < limit:
            selected.append(doc)

    sources = sorted({d.source for d in selected})
    return {
        "relevant_documents": selected,
        "trace": _trace(
            "validate_sources",
            f"{len(selected)} chunks across {len(sources)} document(s)",
            started,
        ),
    }


# ---------------------------------------------------------------------------
# Self-correction
# ---------------------------------------------------------------------------
def rewrite_query(state: AgentState) -> dict[str, Any]:
    """Reformulate the search query after retrieval came back irrelevant.

    The loop counter is incremented here, and ``decide_after_grading`` reads it, so the
    retrieve/grade/rewrite cycle is bounded by ``MAX_QUERY_REWRITES``.
    """
    started = time.perf_counter()
    rewrites = state.get("rewrites", 0) + 1

    rejected = state.get("documents", [])
    failed_note = ""
    if rejected:
        titles = sorted({d.doc_title for d in rejected})[:3]
        failed_note = f"It retrieved these unrelated documents: {', '.join(titles)}."

    try:
        result: RewrittenQuery = _structured(RewrittenQuery).invoke(
            [
                ("system", prompts.REWRITE_SYSTEM),
                (
                    "human",
                    prompts.REWRITE_USER.format(
                        question=state["question"],
                        search_query=state["search_query"],
                        failed_note=failed_note,
                    ),
                ),
            ]
        )
        new_query, strategy = result.query.strip(), result.strategy
    except Exception as exc:  # noqa: BLE001
        log.warning("rewrite_failed", error=str(exc))
        new_query, strategy = state["question"], "rewrite failed; reused original question"

    log.info("rewrote_query", attempt=rewrites, query=new_query, strategy=strategy)
    return {
        "search_query": new_query or state["question"],
        "rewrites": rewrites,
        # Drop the sub-queries so the retry searches the rewritten query, not the old plan.
        "subqueries": [],
        "trace": _trace("rewrite_query", f"attempt {rewrites}: {strategy}", started),
    }


# ---------------------------------------------------------------------------
# Answer generation
# ---------------------------------------------------------------------------
def normalize_citation_markers(answer: str) -> str:
    """Rewrite non-ASCII citation brackets to ``[n]``.

    gpt-oss models intermittently emit CJK fullwidth brackets (U+3010/U+3011) instead of
    square brackets. Left alone these break every downstream consumer that looks for
    ``[n]`` -- the UI's citation linking and the benchmark's citation accounting -- so
    they are normalised at the single point where answers are produced.
    """
    return answer.replace("【", "[").replace("】", "]").replace("［", "[").replace("］", "]")


def _citations_from(documents: list[RetrievedChunk]) -> list[dict]:
    """Build the citation payload the API and UI render."""
    return [
        {
            "n": i,
            "source": doc.source,
            "section": doc.section,
            "doc_title": doc.doc_title,
            "category": doc.category,
            "score": round(doc.score, 4),
            "chunk_id": doc.chunk_id,
            "snippet": doc.text[:280],
        }
        for i, doc in enumerate(documents, start=1)
    ]


def generate(state: AgentState) -> dict[str, Any]:
    """Write the grounded, cited answer from the validated evidence."""
    started = time.perf_counter()
    documents = state.get("relevant_documents", [])

    try:
        response = get_llm("strong").invoke(
            [
                ("system", prompts.GENERATE_SYSTEM),
                (
                    "human",
                    prompts.GENERATE_USER.format(
                        question=state["question"],
                        context=prompts.format_context_for_generation(documents),
                    ),
                ),
            ]
        )
        answer = normalize_citation_markers(response.content.strip())
    except Exception as exc:  # noqa: BLE001
        log.error("generation_failed", error=str(exc))
        return {
            "answer": (
                "I found relevant documentation but could not generate an answer because "
                f"the language model call failed ({exc}). The sources below are the "
                "passages that matched."
            ),
            "citations": _citations_from(documents),
            "insufficient_evidence": False,
            "trace": _trace("generate", f"failed: {exc}", started),
        }

    return {
        "answer": answer,
        "citations": _citations_from(documents),
        "insufficient_evidence": False,
        "trace": _trace("generate", f"{len(answer)} chars, {len(documents)} sources", started),
    }


def direct_answer(state: AgentState) -> dict[str, Any]:
    """Handle greetings and out-of-scope requests without touching the knowledge base."""
    started = time.perf_counter()

    try:
        response = get_llm("fast").invoke(
            [
                ("system", prompts.DIRECT_ANSWER_SYSTEM),
                ("human", prompts.DIRECT_ANSWER_USER.format(question=state["question"])),
            ]
        )
        answer = response.content.strip()
    except Exception as exc:  # noqa: BLE001
        log.warning("direct_answer_failed", error=str(exc))
        answer = (
            "I'm ACME's internal knowledge assistant. I can answer questions about our "
            "technical documentation, operational policies, and business information."
        )

    return {
        "answer": answer,
        "citations": [],
        "insufficient_evidence": False,
        "trace": _trace("direct_answer", f"intent={state.get('intent')}", started),
    }


def fallback(state: AgentState) -> dict[str, Any]:
    """Decline to answer, having exhausted the retry budget.

    Deliberately a fixed string rather than an LLM call. Asking a model to explain that
    it has no evidence is an invitation for it to produce a plausible answer anyway,
    which is precisely the failure this path exists to prevent.
    """
    started = time.perf_counter()
    attempts = state.get("rewrites", 0) + 1

    return {
        "answer": prompts.FALLBACK_ANSWER.format(attempts=attempts),
        "citations": [],
        "insufficient_evidence": True,
        "trace": _trace("fallback", f"no relevant evidence after {attempts} attempts", started),
    }


# ---------------------------------------------------------------------------
# Conditional edges
# ---------------------------------------------------------------------------
def decide_after_routing(state: AgentState) -> str:
    """Send knowledge questions to retrieval and everything else to a direct reply."""
    return "knowledge" if state.get("intent") == "knowledge" else "direct"


def decide_after_grading(state: AgentState) -> str:
    """Choose between answering, retrying with a new query, and giving up.

    This is the self-correcting branch that separates agentic RAG from a linear pipeline,
    and the rewrite budget is what keeps it terminating.
    """
    if state.get("relevant_documents"):
        return "generate"
    if state.get("rewrites", 0) < settings.max_query_rewrites:
        return "rewrite"
    return "fallback"
