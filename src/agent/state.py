"""The LangGraph state object.

Every node receives the whole state and returns a partial update, which LangGraph merges.
Two fields deserve explanation:

``trace``
    An append-only record of which nodes ran, in order, with a short note each. It is
    what the Streamlit UI renders in its "Agent reasoning" panel and what makes the
    self-correction loop visible instead of merely claimed. It uses an ``operator.add``
    reducer so nodes append rather than overwrite.

``rewrites``
    The loop guard. ``decide_after_grading`` routes to the fallback once this reaches
    ``MAX_QUERY_REWRITES``, so the retrieve/grade/rewrite cycle cannot run forever.
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

from src.retrieval.retriever import RetrievedChunk

Intent = Literal["knowledge", "chitchat", "out_of_scope"]


class TraceEntry(TypedDict):
    """One step in the agent's execution path."""

    node: str
    detail: str
    elapsed_ms: int


class AgentState(TypedDict, total=False):
    """State threaded through the graph.

    ``total=False`` because nodes populate fields progressively; only ``question`` is
    present when the graph starts.
    """

    # --- Input ---------------------------------------------------------------
    question: str

    # --- Routing (set by `route_query`) --------------------------------------
    intent: Intent
    category_filter: str | None
    routing_reason: str

    # --- Decomposition (set by `decompose_query`) ----------------------------
    subqueries: list[str]

    # --- Retrieval and grading -----------------------------------------------
    # The query actually sent to the retriever. Starts as `question` and is replaced by
    # `rewrite_query`, so the retry searches for something different from the original.
    search_query: str
    documents: list[RetrievedChunk]
    relevant_documents: list[RetrievedChunk]

    # --- Loop control --------------------------------------------------------
    rewrites: int

    # --- Output --------------------------------------------------------------
    answer: str
    citations: list[dict]
    # True when the agent declined to answer for lack of grounded evidence. Surfaced by
    # the API so a caller can distinguish "no answer" from "an answer".
    insufficient_evidence: bool

    # --- Observability -------------------------------------------------------
    trace: Annotated[list[TraceEntry], operator.add]


def initial_state(question: str) -> AgentState:
    """Build the starting state for a question."""
    return {
        "question": question,
        "search_query": question,
        "rewrites": 0,
        "documents": [],
        "relevant_documents": [],
        "subqueries": [],
        "citations": [],
        "insufficient_evidence": False,
        "trace": [],
    }


def trace_path(state: AgentState) -> str:
    """Render the visited nodes as an arrow-separated path, for logs and the CLI."""
    return " -> ".join(entry["node"] for entry in state.get("trace", []))
