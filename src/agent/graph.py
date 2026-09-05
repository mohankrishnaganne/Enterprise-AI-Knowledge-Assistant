"""The compiled LangGraph workflow.

    START
      |
      v
    route_query --(chitchat / out_of_scope)--> direct_answer --> END
      | knowledge
      v
    decompose_query
      |
      v
    retrieve <-------------------+
      |                          |
      v                          |
    grade_documents              |
      |                          |
      +-- relevant >= 1 --> validate_sources --> generate --> END
      |                                                       |
      +-- relevant == 0, rewrites < MAX --> rewrite_query -----+
      |
      +-- relevant == 0, rewrites == MAX --> fallback --> END

The cycle back into ``retrieve`` is the whole point: a linear RAG pipeline answers from
whatever it retrieved first, while this one notices the evidence is bad, searches
differently, and declines rather than guessing when that also fails.

Run it directly::

    python -m src.agent.graph "What is ACME's incident escalation policy?"
"""

from __future__ import annotations

import argparse
import sys
import time
from functools import lru_cache
from typing import Any

from langgraph.graph import END, START, StateGraph

from src.agent import nodes
from src.agent.state import AgentState, initial_state, trace_path
from src.logging_conf import get_logger

log = get_logger(__name__)


def build_graph() -> StateGraph:
    """Wire the nodes and edges.

    Separate from :func:`compile_graph` so tests can inspect the topology without
    compiling or invoking anything.
    """
    workflow = StateGraph(AgentState)

    workflow.add_node("route_query", nodes.route_query)
    workflow.add_node("decompose_query", nodes.decompose_query)
    workflow.add_node("retrieve", nodes.retrieve)
    workflow.add_node("grade_documents", nodes.grade_documents)
    workflow.add_node("validate_sources", nodes.validate_sources)
    workflow.add_node("generate", nodes.generate)
    workflow.add_node("rewrite_query", nodes.rewrite_query)
    workflow.add_node("direct_answer", nodes.direct_answer)
    workflow.add_node("fallback", nodes.fallback)

    workflow.add_edge(START, "route_query")

    # Knowledge questions go to retrieval; everything else is answered directly.
    workflow.add_conditional_edges(
        "route_query",
        nodes.decide_after_routing,
        {"knowledge": "decompose_query", "direct": "direct_answer"},
    )

    workflow.add_edge("decompose_query", "retrieve")
    workflow.add_edge("retrieve", "grade_documents")

    # The self-correction branch.
    workflow.add_conditional_edges(
        "grade_documents",
        nodes.decide_after_grading,
        {
            "generate": "validate_sources",
            "rewrite": "rewrite_query",
            "fallback": "fallback",
        },
    )

    # The cycle: a rewritten query goes back through retrieval and grading.
    workflow.add_edge("rewrite_query", "retrieve")

    workflow.add_edge("validate_sources", "generate")
    workflow.add_edge("generate", END)
    workflow.add_edge("direct_answer", END)
    workflow.add_edge("fallback", END)

    return workflow


@lru_cache(maxsize=1)
def compile_graph():
    """Return the compiled graph.

    Cached because compilation is not free and the FastAPI app must not repeat it per
    request. ``recursion_limit`` is enforced at invocation rather than here.
    """
    graph = build_graph().compile()
    log.info("graph_compiled", nodes=len(graph.get_graph().nodes))
    return graph


def _recursion_limit() -> int:
    """A ceiling that permits every legitimate retry and nothing beyond it.

    Longest legal path: route + decompose, then (retrieve + grade + rewrite) per retry,
    then retrieve + grade + validate + generate. The margin keeps LangGraph's own
    accounting from tripping on a path the design allows.
    """
    from src.config import settings

    return 2 + 3 * settings.max_query_rewrites + 4 + 5


def answer_question(question: str) -> dict[str, Any]:
    """Run the graph for one question and return a serialisable result.

    Returns:
        ``answer``, ``citations``, ``trace``, ``intent``, ``rewrites``,
        ``insufficient_evidence`` and ``latency_ms``.
    """
    started = time.perf_counter()
    graph = compile_graph()

    final: AgentState = graph.invoke(
        initial_state(question),
        config={"recursion_limit": _recursion_limit()},
    )

    latency_ms = int((time.perf_counter() - started) * 1000)
    result = {
        "question": question,
        "answer": final.get("answer", ""),
        "citations": final.get("citations", []),
        # Full text of the passages the answer was written from. Not part of the HTTP
        # response (it would bloat every payload), but the evaluation harness needs it:
        # scoring faithfulness against the truncated citation snippets judges claims
        # against context the model never saw, and reports near-zero for a perfectly
        # grounded answer. Measured: 1.0 with full chunks, 0.0 with 280-char snippets.
        "contexts": [doc.text for doc in final.get("relevant_documents", [])],
        "trace": final.get("trace", []),
        "path": trace_path(final),
        "intent": final.get("intent", "knowledge"),
        "category_filter": final.get("category_filter"),
        "rewrites": final.get("rewrites", 0),
        "insufficient_evidence": final.get("insufficient_evidence", False),
        "latency_ms": latency_ms,
    }
    log.info(
        "question_answered",
        path=result["path"],
        rewrites=result["rewrites"],
        citations=len(result["citations"]),
        latency_ms=latency_ms,
    )
    return result


def _use_utf8_stdout() -> None:
    """Force UTF-8 on the console.

    Windows terminals default to cp1252, which cannot encode characters the model
    routinely emits (non-breaking hyphens, curly quotes, em dashes). Without this the CLI
    crashes on a perfectly good answer. ``errors="replace"`` keeps a legacy console
    usable rather than trading one crash for another.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _print_result(result: dict[str, Any]) -> None:
    """Render a result for the terminal."""
    print("\n" + "=" * 78)
    print(f"Q: {result['question']}")
    print("=" * 78)
    print(f"\n{result['answer']}\n")

    if result["citations"]:
        print("-" * 78)
        print("Sources")
        for citation in result["citations"]:
            section = f" > {citation['section']}" if citation["section"] else ""
            print(f"  [{citation['n']}] {citation['source']}{section}  (score {citation['score']})")

    print("-" * 78)
    print("Agent path")
    for entry in result["trace"]:
        print(f"  {entry['node']:<18} {entry['detail']:<52} {entry['elapsed_ms']:>6} ms")
    print(
        f"\n  intent={result['intent']}  filter={result['category_filter']}  "
        f"rewrites={result['rewrites']}  total={result['latency_ms']} ms\n"
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: run one question through the graph."""
    _use_utf8_stdout()
    parser = argparse.ArgumentParser(description="Ask the knowledge assistant a question.")
    parser.add_argument("question", nargs="*", help="The question to ask.")
    parser.add_argument(
        "--check", action="store_true", help="Verify configuration and exit without asking."
    )
    args = parser.parse_args(argv)

    from src.agent.llm import check_models_available

    problems = check_models_available()
    if problems:
        print("\nConfiguration problem:\n")
        for problem in problems:
            print(f"  - {problem}")
        print()
        return 1

    if args.check:
        print("\nConfiguration OK: both Groq models are available.\n")
        return 0

    question = " ".join(args.question).strip()
    if not question:
        parser.error("provide a question, or use --check")

    _print_result(answer_question(question))
    return 0


if __name__ == "__main__":
    sys.exit(main())
