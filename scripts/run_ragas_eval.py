"""Evaluate answer quality with RAGAS and write ``reports/ragas_scores.md``.

Runs each golden question through the **full LangGraph agent** -- routing, decomposition,
retrieval, grading, any rewrites -- and scores the answers it actually produces. Scoring a
bare retrieve-and-generate chain instead would measure a system that is not the one being
shipped.

    python scripts/run_ragas_eval.py            # the 5-question demo subset
    python scripts/run_ragas_eval.py --all      # every answerable question
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import REPORTS_DIR, settings  # noqa: E402
from src.evaluation.golden import GoldenQuestion, answerable, load, validate  # noqa: E402
from src.evaluation.ragas_runner import METRIC_NAMES, evaluate_samples  # noqa: E402
from src.logging_conf import get_logger  # noqa: E402

log = get_logger(__name__)

REPORT_PATH = REPORTS_DIR / "ragas_scores.md"

# What each metric means, in the report, so a reader does not have to look them up.
METRIC_DESCRIPTIONS = {
    "faithfulness": (
        "Fraction of claims in the answer that are supported by the retrieved context. "
        "This is the hallucination measure: 1.0 means every claim is grounded."
    ),
    "answer_relevancy": (
        "Whether the answer addresses the question asked. Computed by generating "
        "questions from the answer and comparing them to the original in embedding space."
    ),
    "context_precision": (
        "Whether the context that mattered was ranked highly, judged by an LLM against "
        "the reference answer."
    ),
    "context_recall": (
        "Whether the retrieved context covers the reference answer. Low values mean the "
        "retriever missed something the answer needed."
    ),
}


def collect_samples(questions: list[GoldenQuestion]) -> tuple[list[dict], list[dict]]:
    """Run the agent over each question and shape the results for RAGAS.

    Returns:
        ``(samples, run_details)`` -- the RAGAS payload, and per-question agent metadata
        (path taken, rewrites, latency) that goes into the report alongside the scores.
    """
    from src.agent.graph import answer_question

    samples: list[dict] = []
    details: list[dict] = []

    for i, question in enumerate(questions, start=1):
        print(f"  [{i}/{len(questions)}] {question.id}: {question.question[:58]}…", flush=True)
        result = answer_question(question.question)

        # Full chunk text, not the truncated citation snippets -- see the note in
        # src/agent/graph.py:answer_question. Truncated context makes faithfulness
        # report ~0 for correctly grounded answers.
        contexts = result["contexts"]
        samples.append(
            {
                "user_input": question.question,
                "response": result["answer"],
                "retrieved_contexts": contexts,
                "reference": question.ground_truth,
            }
        )
        details.append(
            {
                "id": question.id,
                "question": question.question,
                "path": result["path"],
                "rewrites": result["rewrites"],
                "citations": len(result["citations"]),
                "declined": result["insufficient_evidence"],
                "latency_ms": result["latency_ms"],
            }
        )

    return samples, details


def render_report(
    scores, details: list[dict], questions: list[GoldenQuestion], elapsed: float
) -> str:
    """Render the markdown report."""
    lines: list[str] = []
    add = lines.append

    add("# RAGAS Evaluation")
    add("")
    add(
        f"_Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} by "
        "`scripts/run_ragas_eval.py`. Regenerate with `make eval`._"
    )
    add("")

    add("## Scores")
    add("")
    add("| Metric | Score | What it measures |")
    add("| --- | ---: | --- |")
    for name in METRIC_NAMES:
        value = scores.get(name)
        rendered = f"{value:.3f}" if value is not None else "—"
        add(f"| `{name}` | **{rendered}** | {METRIC_DESCRIPTIONS[name]} |")
    add("")
    add(
        f"Judge model: `{scores.judge_model or settings.groq_model_strong}` (Groq). "
        f"Embeddings: `{settings.embedding_model}` (local). Both free-tier, so this "
        "evaluation costs nothing to reproduce."
    )
    add("")

    if scores.failures:
        add("### Issues during evaluation")
        add("")
        for failure in scores.failures:
            add(f"- {failure}")
        add("")

    add("## What was evaluated")
    add("")
    add(
        f"Each of the {len(questions)} questions was run through the **full LangGraph "
        "agent** — routing, decomposition, retrieval, LLM grading, and any query "
        "rewrites — and the answer it actually produced was scored. Evaluating a bare "
        "retrieve-and-generate chain would measure a system that is not the one being "
        "shipped."
    )
    add("")

    add("| Question | Path | Rewrites | Sources | Latency |")
    add("| --- | --- | ---: | ---: | ---: |")
    for detail in details:
        short_path = detail["path"].replace("route_query -> ", "").replace(" -> ", " → ")
        add(
            f"| `{detail['id']}` {detail['question'][:44]} | {short_path[:60]} | "
            f"{detail['rewrites']} | {detail['citations']} | "
            f"{detail['latency_ms'] / 1000:.1f}s |"
        )
    add("")

    if scores.per_sample:
        add("## Per-question scores")
        add("")
        header = "| Question | " + " | ".join(f"`{n}`" for n in METRIC_NAMES) + " |"
        add(header)
        add("| --- | " + " | ".join("---:" for _ in METRIC_NAMES) + " |")
        for sample in scores.per_sample:
            cells = []
            for name in METRIC_NAMES:
                value = sample.get(name)
                try:
                    cells.append(f"{float(value):.3f}")
                except (TypeError, ValueError):
                    cells.append("—")
            add(f"| {sample['question'][:52]} | " + " | ".join(cells) + " |")
        add("")

    add("## Interpretation and limitations")
    add("")
    add(
        "- **Faithfulness is the metric that matters most here.** The whole premise of "
        "this system is that answers are grounded in retrieved passages; a high "
        "faithfulness score is evidence that the citation discipline in the generation "
        "prompt actually holds."
    )
    add(
        "- **Context is taken from the citations the agent returned**, i.e. after LLM "
        "grading and source validation. That is the context the answer was genuinely "
        "written from, so it is the honest input to these metrics."
    )
    add(
        "- **Questions the agent declined are excluded.** A refusal has no retrieved "
        "context, and faithfulness against empty context is undefined rather than zero. "
        "Scoring them as 0 would understate the system for behaving correctly."
    )
    add(
        f"- **Small sample ({len(questions)} questions).** These scores show a direction, "
        "not a confidence interval. The judge is also an LLM, so scores vary a little "
        "between runs even at temperature 0."
    )
    add(
        "- The retrieval side is measured separately and more rigorously in "
        "[`retrieval_benchmark.md`](retrieval_benchmark.md), which uses a deterministic "
        "relevance rule and a held-out test split rather than LLM judgement."
    )
    add("")
    add(f"_Run took {elapsed:.0f}s._")
    add("")

    return "\n".join(lines)


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Score the agent's answers with RAGAS.")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Evaluate every answerable question, not the demo subset.",
    )
    parser.add_argument(
        "--limit", type=int, default=5, help="How many questions to evaluate (default 5)."
    )
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    problems = validate()
    if problems:
        print("\nGolden dataset is inconsistent with the corpus; refusing to evaluate:\n")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    questions = answerable(load())
    if not args.all:
        questions = questions[: args.limit]

    started = time.perf_counter()

    print(f"\nRunning {len(questions)} questions through the full agent…")
    samples, details = collect_samples(questions)

    print("\nScoring with RAGAS (judge calls are serialised to respect Groq rate limits)…")
    scores = evaluate_samples(samples)

    elapsed = time.perf_counter() - started
    report = render_report(scores, details, questions, elapsed)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")

    print("\n" + "=" * 70)
    print("RAGAS SCORES")
    print("=" * 70)
    for name in METRIC_NAMES:
        value = scores.get(name)
        print(f"  {name:<20} {f'{value:.3f}' if value is not None else '—'}")
    print("=" * 70)
    for failure in scores.failures:
        print(f"  ! {failure}")
    print(f"\n  Report written to {REPORT_PATH}\n")

    return 0 if not scores.failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
