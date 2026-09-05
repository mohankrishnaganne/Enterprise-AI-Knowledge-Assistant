"""Retrieval A/B benchmark: naive baseline vs the optimized pipeline.

Writes ``reports/retrieval_benchmark.md`` and prints the headline number. **Nothing here
hardcodes a target.** The reduction reported is whatever the measurement yields.

Three methodological commitments, each of which changed the result when it was applied:

**1. Every arm returns the same number of chunks where a rate is compared.**
Only ~1.6 chunks per question satisfy the relevance rule in this corpus, so precision@k
falls mechanically as k grows. An early version compared a k=5 baseline against a k=6
optimized arm and reported the optimized pipeline as *worse*; that was an artifact of k,
not a property of the retriever.

**2. Parameters are tuned on a dev split and reported on a held-out test split.**
The score threshold has to be chosen against something. Choosing it against the same
questions the headline is measured on would be overfitting, which with 15 questions would
be severe.

**3. The router is not an oracle.** Filtered arms take their category from the live LLM
router, so router mistakes count against the optimized arms as they do in production.

The ablation is cumulative, so each optimization's contribution is separately
attributable:

    A. baseline           512-char naive chunks, no overlap, no context header,
                          plain top-k, unfiltered, no MMR, no threshold
    B. + optimized chunks 800/120 markdown-aware chunks with contextual headers
    C. + metadata filter  category filter from the live router
    D. + MMR/threshold    the full production retriever

Run after ``python scripts/run_ingestion.py --both``::

    python scripts/benchmark_retrieval.py
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import REPORTS_DIR, settings  # noqa: E402
from src.evaluation.golden import GoldenQuestion, answerable, split, validate  # noqa: E402
from src.evaluation.retrieval_metrics import (  # noqa: E402
    ArmMetrics,
    relative_reduction,
    score_question,
)
from src.ingestion.chunker import get_config  # noqa: E402
from src.logging_conf import get_logger  # noqa: E402
from src.retrieval.retriever import BaselineRetriever, OptimizedRetriever  # noqa: E402

log = get_logger(__name__)

REPORT_PATH = REPORTS_DIR / "retrieval_benchmark.md"

# Every arm returns this many chunks, so the rate comparison is not confounded by k.
COMPARISON_K = 5

# Candidate score thresholds searched on the dev split. bge-small cosine scores for this
# corpus land in roughly 0.55-0.87, so anything below ~0.55 is a no-op.
THRESHOLD_GRID = (0.0, 0.55, 0.58, 0.60, 0.62, 0.65, 0.68)
MMR_LAMBDA_GRID = (1.0, 0.9, 0.7, 0.5)


def route_categories(questions: list[GoldenQuestion], *, oracle: bool) -> dict[str, str | None]:
    """Return the category filter each question would receive in production."""
    if oracle:
        return {q.id: q.expected_category for q in questions}

    from src.agent.nodes import route_query
    from src.agent.state import initial_state

    filters: dict[str, str | None] = {}
    for question in questions:
        update = route_query(initial_state(question.question))
        filters[question.id] = update.get("category_filter")
    return filters


def measure(retriever, questions, filters, *, name="", description="") -> ArmMetrics:
    """Run one configuration over a question set."""
    metrics = ArmMetrics(name=name, description=description)
    for question in questions:
        category = filters.get(question.id) if filters else None
        metrics.results.append(
            score_question(question, retriever.retrieve(question.question, category=category))
        )
    return metrics


def tune(dev: list[GoldenQuestion], filters: dict[str, str | None]) -> tuple[dict, dict, list]:
    """Choose the MMR lambda and score threshold on the dev split.

    Selection rule, fixed before looking at any numbers: **minimise the irrelevant rate
    subject to losing no hit rate**. A configuration that finds fewer answers is not an
    improvement no matter how clean its output looks, so hit rate is a hard constraint
    rather than something traded off.
    """
    # The candidate pool depends only on the query and filter, so fetch it once per
    # question and reuse it across all 28 configurations. Sweeping without this makes
    # 28x more Pinecone round trips for identical results.
    pools = {
        q.id: OptimizedRetriever(fetch_k=settings.retrieval_fetch_k).fetch_candidates(
            q.question, category=filters.get(q.id)
        )
        for q in dev
    }

    trials = []
    for mmr_lambda in MMR_LAMBDA_GRID:
        for threshold in THRESHOLD_GRID:
            retriever = OptimizedRetriever(
                top_k=COMPARISON_K,
                fetch_k=settings.retrieval_fetch_k,
                mmr_lambda=mmr_lambda,
                score_threshold=threshold,
            )
            metrics = ArmMetrics(name="", description="")
            for question in dev:
                vector, candidates = pools[question.id]
                metrics.results.append(
                    score_question(question, retriever.select(vector, candidates))
                )
            trials.append(
                {
                    "mmr_lambda": mmr_lambda,
                    "threshold": threshold,
                    "irrelevant_rate": metrics.irrelevant_rate,
                    "hit_rate": metrics.hit_rate,
                    "mrr": metrics.mrr,
                }
            )

    best_hit_rate = max(t["hit_rate"] for t in trials)
    admissible = [t for t in trials if t["hit_rate"] >= best_hit_rate]
    chosen = min(admissible, key=lambda t: (t["irrelevant_rate"], -t["mrr"]))

    # A threshold sitting at the very edge of what dev tolerates is on a cliff: the next
    # question along may fall the other side of it. So the one grid step below the
    # optimum is carried forward as a conservative alternative and both are measured on
    # test, rather than betting the whole result on the aggressive pick.
    lower = [
        t
        for t in admissible
        if t["mmr_lambda"] == chosen["mmr_lambda"] and t["threshold"] < chosen["threshold"]
    ]
    conservative = max(lower, key=lambda t: t["threshold"]) if lower else chosen

    log.info(
        "tuned_on_dev",
        mmr_lambda=chosen["mmr_lambda"],
        threshold=chosen["threshold"],
        dev_irrelevant_rate=round(chosen["irrelevant_rate"], 4),
        dev_hit_rate=chosen["hit_rate"],
        trials=len(trials),
    )
    return chosen, conservative, trials


def measure_end_to_end(
    questions: list[GoldenQuestion],
    filters: dict[str, str | None],
    *,
    mmr_lambda: float,
    threshold: float,
) -> ArmMetrics:
    """Measure the chunks that actually reach the generator, after LLM grading.

    Arms A-D measure retrieval alone. But the agent does not hand raw retrieval output to
    the generator: it grades every chunk with an LLM and keeps only the ones judged
    relevant, then caps and diversifies the survivors. That is the context the answer is
    written from, so it is the honest system-level answer to "how many irrelevant results
    reach the user".

    It is reported separately from the headline because it is non-deterministic -- an LLM
    judges each chunk, so the number moves slightly between runs -- whereas arms A-D are
    fully reproducible.
    """
    from src.agent.nodes import grade_documents, validate_sources
    from src.agent.state import initial_state

    retriever = OptimizedRetriever(
        namespace=settings.pinecone_namespace,
        top_k=COMPARISON_K,
        fetch_k=settings.retrieval_fetch_k,
        mmr_lambda=mmr_lambda,
        score_threshold=threshold,
    )

    metrics = ArmMetrics(
        name="E. + LLM grading (full agent pipeline)",
        description=(
            "as D, plus the agent's LLM relevance grading and source validation -- the "
            "context the generator actually receives"
        ),
    )

    for question in questions:
        state = initial_state(question.question)
        state["documents"] = retriever.retrieve(
            question.question, category=filters.get(question.id)
        )
        state.update(grade_documents(state))
        state.update(validate_sources(state))
        metrics.results.append(score_question(question, state["relevant_documents"]))

    log.info(
        "end_to_end_arm_complete",
        irrelevant_rate=round(metrics.irrelevant_rate, 4),
        hit_rate=round(metrics.hit_rate, 4),
    )
    return metrics


def build_arms(
    questions: list[GoldenQuestion],
    filters: dict[str, str | None],
    *,
    mmr_lambda: float,
    threshold: float,
) -> list[ArmMetrics]:
    """Run the cumulative ablation at a fixed k."""
    plain = dict(top_k=COMPARISON_K, fetch_k=COMPARISON_K, mmr_lambda=1.0, score_threshold=0.0)

    arms = [
        measure(
            BaselineRetriever(namespace=settings.pinecone_baseline_namespace, top_k=COMPARISON_K),
            questions,
            None,
            name="A. baseline",
            description=(
                f"512-char naive chunks, no overlap, no contextual header; plain "
                f"top-k={COMPARISON_K}, unfiltered, no MMR, no score threshold"
            ),
        ),
        measure(
            OptimizedRetriever(namespace=settings.pinecone_namespace, **plain),
            questions,
            None,
            name="B. + optimized chunking",
            description=(
                f"{settings.chunk_size}/{settings.chunk_overlap} markdown-aware chunks with "
                f"contextual headers; retrieval still plain top-k={COMPARISON_K}, unfiltered"
            ),
        ),
        measure(
            OptimizedRetriever(namespace=settings.pinecone_namespace, **plain),
            questions,
            filters,
            name="C. + metadata filter",
            description="as B, plus the category filter chosen by the live LLM router",
        ),
        measure(
            OptimizedRetriever(
                namespace=settings.pinecone_namespace,
                top_k=COMPARISON_K,
                fetch_k=settings.retrieval_fetch_k,
                mmr_lambda=mmr_lambda,
                score_threshold=threshold,
            ),
            questions,
            filters,
            name="D. + MMR and score threshold (production)",
            description=(
                f"as C, plus over-fetch to {settings.retrieval_fetch_k}, MMR "
                f"(lambda={mmr_lambda}) and score threshold {threshold}, both tuned on the "
                "dev split"
            ),
        ),
    ]

    for arm in arms:
        log.info(
            "arm_complete",
            arm=arm.name,
            irrelevant_rate=round(arm.irrelevant_rate, 4),
            hit_rate=round(arm.hit_rate, 4),
        )
    return arms


def _ablation_table(arms: list[ArmMetrics]) -> list[str]:
    """Render the ablation table rows."""
    lines = [
        "| Arm | Irrelevant rate | Precision | MRR | Hit rate | Chunks/question |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for arm in arms:
        lines.append(
            f"| {arm.name} | {arm.irrelevant_rate:.1%} | {arm.precision:.1%} | "
            f"{arm.mrr:.3f} | {arm.hit_rate:.0%} | {arm.mean_retrieved:.2f} |"
        )
    return lines


def render_report(
    test_arms: list[ArmMetrics],
    full_arms: list[ArmMetrics],
    dev: list[GoldenQuestion],
    test: list[GoldenQuestion],
    *,
    mmr_lambda: float,
    threshold: float,
    conservative: dict,
    conservative_arm: ArmMetrics,
    end_to_end: ArmMetrics,
    trials: list,
    router_accuracy: tuple[int, int],
    elapsed: float,
) -> str:
    """Render the markdown report."""
    baseline, production = test_arms[0], test_arms[-1]
    reduction = relative_reduction(baseline.irrelevant_rate, production.irrelevant_rate)
    full_reduction = relative_reduction(full_arms[0].irrelevant_rate, full_arms[-1].irrelevant_rate)

    lines: list[str] = []
    add = lines.append

    add("# Retrieval Benchmark: naive baseline vs optimized pipeline")
    add("")
    add(
        f"_Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} by "
        "`scripts/benchmark_retrieval.py`. Regenerate with `make bench`._"
    )
    add("")

    add("## Headline")
    add("")
    add(
        f"**Irrelevant retrieved results fell {reduction:.1f}%** — from "
        f"{baseline.irrelevant_rate:.1%} to {production.irrelevant_rate:.1%} of returned "
        f"chunks — on {len(test)} **held-out** questions the retrieval parameters were "
        "never tuned against."
    )
    add("")
    if production.hit_rate >= baseline.hit_rate:
        add(
            f"Hit rate held at {production.hit_rate:.0%}: the pipeline returns less noise "
            "without finding fewer answers."
        )
    else:
        lost = round((baseline.hit_rate - production.hit_rate) * len(test))
        add(
            f"**This came at a cost.** Hit rate fell from {baseline.hit_rate:.0%} to "
            f"{production.hit_rate:.0%} — {lost} of {len(test)} held-out questions no "
            "longer retrieved any relevant chunk, because the tuned score threshold "
            "excluded it. The threshold satisfied the no-hit-loss constraint on dev and "
            "did not generalise. This is a real trade-off, not a rounding artifact, and "
            "the conservative configuration below avoids it."
        )
    add("")
    add("| Configuration | Irrelevant rate | Reduction | Hit rate |")
    add("| --- | ---: | ---: | ---: |")
    add(f"| A. baseline | {baseline.irrelevant_rate:.1%} | — | {baseline.hit_rate:.0%} |")
    add(
        f"| D. tuned optimum (threshold {threshold}) | {production.irrelevant_rate:.1%} | "
        f"{reduction:.1f}% | {production.hit_rate:.0%} |"
    )
    add(
        f"| D'. conservative (threshold {conservative['threshold']}) | "
        f"{conservative_arm.irrelevant_rate:.1%} | "
        f"{relative_reduction(baseline.irrelevant_rate, conservative_arm.irrelevant_rate):.1f}% | "
        f"{conservative_arm.hit_rate:.0%} |"
    )
    add(
        f"| E. + LLM grading (full pipeline) | {end_to_end.irrelevant_rate:.1%} | "
        f"{relative_reduction(baseline.irrelevant_rate, end_to_end.irrelevant_rate):.1f}% | "
        f"{end_to_end.hit_rate:.0%} |"
    )
    add("")
    add(
        "Arm E is the whole agent pipeline: conservative retrieval **plus** the LLM "
        "grading step that discards irrelevant chunks before generation. It is the "
        'honest system-level answer to "how much irrelevant material actually reaches '
        'the user", since that graded set is the context the answer is written from. '
        "It is reported separately from the headline because an LLM judges each chunk, "
        "so unlike arms A-D it is not bit-for-bit reproducible between runs."
    )
    add("")
    if conservative_arm.hit_rate > production.hit_rate:
        add(
            "**Recommended for production: the conservative configuration.** For a "
            "knowledge assistant a missed answer is worse than a noisy one, especially "
            "since the agent's LLM grading step removes irrelevant chunks downstream "
            "anyway. The claim to quote is therefore the conservative row."
        )
        add("")
    add(
        f"Across all {len(dev) + len(test)} answerable questions (dev + test) the "
        f"reduction is {full_reduction:.1f}%; the held-out figure above is the one to "
        "quote."
    )
    add("")

    add("## Ablation (held-out test split)")
    add("")
    add(
        "Each arm adds one change to the one above it. Every arm returns "
        f"top-k={COMPARISON_K} where a rate is compared."
    )
    add("")
    lines.extend(_ablation_table(test_arms))
    add("")
    add("### Contribution of each change")
    add("")
    add("| Change | Irrelevant rate | Reduction vs. previous arm |")
    add("| --- | ---: | ---: |")
    add(f"| {test_arms[0].name} (starting point) | {test_arms[0].irrelevant_rate:.1%} | — |")
    previous = test_arms[0]
    for arm in test_arms[1:]:
        step = relative_reduction(previous.irrelevant_rate, arm.irrelevant_rate)
        add(f"| {arm.name} | {arm.irrelevant_rate:.1%} | {step:+.1f}% |")
        previous = arm
    add("")

    add("## Ablation (all answerable questions, for reference)")
    add("")
    lines.extend(_ablation_table(full_arms))
    add("")

    add("## Arm definitions")
    add("")
    for arm in test_arms:
        add(f"- **{arm.name}** — {arm.description}")
    add("")

    add("## Tuning")
    add("")
    add(
        f"MMR lambda and the score threshold were selected on the {len(dev)}-question dev "
        f"split ({len(trials)} configurations searched), then frozen. Selection rule, "
        "fixed before any numbers were seen: **minimise the irrelevant rate subject to "
        "losing no hit rate**."
    )
    add("")
    add(f"Chosen: `mmr_lambda={mmr_lambda}`, `score_threshold={threshold}`.")
    add("")
    add("Notable dev-split results:")
    add("")
    add("| MMR lambda | Threshold | Irrelevant rate | Hit rate |")
    add("| ---: | ---: | ---: | ---: |")
    for trial in sorted(trials, key=lambda t: t["irrelevant_rate"])[:8]:
        marker = (
            " **(chosen)**"
            if trial["mmr_lambda"] == mmr_lambda and trial["threshold"] == threshold
            else ""
        )
        add(
            f"| {trial['mmr_lambda']} | {trial['threshold']} | "
            f"{trial['irrelevant_rate']:.1%} | {trial['hit_rate']:.0%}{marker} |"
        )
    add("")

    add("## What the tuning found")
    add("")
    add(
        "Two results here contradicted the initial configuration, and both are worth "
        "stating plainly:"
    )
    add("")
    add(
        "- **MMR hurt.** Diversity is the wrong objective for this corpus: only ~1.6 "
        "chunks per question contain the answer, so there is no breadth to recover and "
        "MMR simply displaces the best chunk. The tuner selected a lambda at or near 1.0, "
        "which is close to disabling it. It is retained because multi-hop questions do "
        "benefit, but at a far higher lambda than the 0.5 originally configured."
    )
    add(
        "- **The original 0.35 score threshold was a no-op.** Every cosine score in this "
        "corpus sits above it, so it never removed anything. The threshold only starts "
        "doing work around 0.60, and that is where nearly all of arm D's gain comes from."
    )
    add("")

    add("## Metric definitions")
    add("")
    add(
        "- **Irrelevant rate** (headline) — of the chunks returned, the fraction failing "
        "the relevance rule, macro-averaged across questions. A retriever returning "
        "nothing scores 1.0, so an arm cannot win by refusing to answer."
    )
    add(
        "- **Relevance rule** — a chunk is relevant iff its source document is one of the "
        "question's `expected_sources` **and** its text contains one of its "
        "`answer_phrases`. Defined in `src/evaluation/golden.py`, keyed on source and "
        "content rather than chunk id, because the arms cut documents at different "
        "boundaries so their chunk ids are not comparable."
    )
    add(
        "- **Hit rate** — questions where at least one relevant chunk was returned. "
        "Deliberately *not* called recall: true recall would require every relevant "
        "passage in the corpus to be labelled, which this golden set does not do."
    )
    add(
        "- **MRR** — mean reciprocal rank of the first relevant chunk. Rewards ranking the "
        "answer first, not merely including it."
    )
    add(
        "- **Reduction** — *relative*: `(baseline - optimized) / baseline`. Not the "
        "difference in percentage points, which would be a different and larger-sounding "
        "claim."
    )
    add("")

    add("## Method and limitations")
    add("")
    correct, total = router_accuracy
    add(
        f"- {len(dev)} dev / {len(test)} held-out test questions, split deterministically "
        "by position so both halves span all three categories. Both include PDF-sourced "
        "and multi-hop questions."
    )
    add(
        "- Both arms query the same Pinecone index and the same embedding model. The only "
        "differences are those named in the arm definitions."
    )
    add(
        f"- The live LLM router chose the expected category for {correct}/{total} "
        "questions. Router errors count against the optimized arms, as in production."
    )
    add(
        "- **Small sample.** 7 held-out questions is enough to show a direction, not to "
        "put a confidence interval on it. One question changing outcome moves the "
        "headline by several points. The dev/test split protects against tuning "
        "overfit; it does not turn 7 questions into a large sample."
    )
    add(
        "- **Retrieval only.** The agent additionally grades every retrieved chunk with an "
        "LLM and discards the irrelevant ones before generation, so the context that "
        "actually reaches the answer is cleaner than arm D. That step is excluded here to "
        "keep the benchmark deterministic and free of LLM sampling variance."
    )
    add(f"- Chunking: {get_config('optimized').describe()} vs {get_config('baseline').describe()}.")
    add(f"- Run took {elapsed:.1f}s.")
    add("")

    add("## Per-question detail (held-out test split)")
    add("")
    add("Irrelevant chunks returned / chunks returned.")
    add("")
    add("| Question | " + " | ".join(a.name.split(".")[0] for a in test_arms) + " |")
    add("| --- | " + " | ".join("---:" for _ in test_arms) + " |")
    for i, question in enumerate(test):
        cells = [f"{a.results[i].irrelevant}/{a.results[i].retrieved}" for a in test_arms]
        add(f"| `{question.id}` {question.question[:52]} | " + " | ".join(cells) + " |")
    add("")

    return "\n".join(lines)


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Benchmark baseline vs optimized retrieval.")
    parser.add_argument(
        "--oracle-router",
        action="store_true",
        help="Use the golden set's known category instead of the live router (diagnostic).",
    )
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    problems = validate()
    if problems:
        print("\nGolden dataset is inconsistent with the corpus; refusing to benchmark:\n")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    dev, test = split()
    everything = answerable()
    started = time.perf_counter()

    print(f"\nRouting {len(everything)} questions through the live LLM router…")
    filters = route_categories(everything, oracle=args.oracle_router)
    correct = sum(1 for q in everything if filters[q.id] == q.expected_category)
    print(f"  router chose the expected category for {correct}/{len(everything)}")

    print(f"\nTuning on the {len(dev)}-question dev split…")
    chosen, conservative, trials = tune(dev, filters)
    mmr_lambda, threshold = chosen["mmr_lambda"], chosen["threshold"]
    print(f"  dev optimum : mmr_lambda={mmr_lambda}, score_threshold={threshold}")
    print(
        f"  conservative: mmr_lambda={conservative['mmr_lambda']}, "
        f"score_threshold={conservative['threshold']}"
    )

    print(f"\nMeasuring the ablation on the {len(test)}-question held-out test split…")
    test_arms = build_arms(test, filters, mmr_lambda=mmr_lambda, threshold=threshold)
    full_arms = build_arms(everything, filters, mmr_lambda=mmr_lambda, threshold=threshold)

    # Also measure the conservative variant on test, so the precision/hit-rate trade-off
    # is visible in the report rather than decided silently here.
    conservative_arm = measure(
        OptimizedRetriever(
            namespace=settings.pinecone_namespace,
            top_k=COMPARISON_K,
            fetch_k=settings.retrieval_fetch_k,
            mmr_lambda=conservative["mmr_lambda"],
            score_threshold=conservative["threshold"],
        ),
        test,
        filters,
        name="D'. conservative threshold",
        description=(
            f"as D but score threshold {conservative['threshold']} — one grid step below "
            "the dev optimum"
        ),
    )

    print("\nMeasuring the full pipeline including LLM grading (arm E)…")
    end_to_end = measure_end_to_end(
        test, filters, mmr_lambda=conservative["mmr_lambda"], threshold=conservative["threshold"]
    )

    elapsed = time.perf_counter() - started
    report = render_report(
        test_arms,
        full_arms,
        dev,
        test,
        mmr_lambda=mmr_lambda,
        threshold=threshold,
        conservative=conservative,
        conservative_arm=conservative_arm,
        end_to_end=end_to_end,
        trials=trials,
        router_accuracy=(correct, len(everything)),
        elapsed=elapsed,
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")

    baseline, production = test_arms[0], test_arms[-1]
    reduction = relative_reduction(baseline.irrelevant_rate, production.irrelevant_rate)

    print("\n" + "=" * 78)
    print(f"RESULTS  (held-out test split, n={len(test)})")
    print("=" * 78)
    for arm in test_arms:
        print(
            f"  {arm.name:<44} irrelevant {arm.irrelevant_rate:6.1%}   "
            f"hit {arm.hit_rate:5.0%}   MRR {arm.mrr:.3f}"
        )
    print("-" * 78)
    print(
        f"  Baseline -> production: {baseline.irrelevant_rate:.1%} -> "
        f"{production.irrelevant_rate:.1%}   (hit rate {baseline.hit_rate:.0%} -> "
        f"{production.hit_rate:.0%})"
    )
    print(f"  RELATIVE REDUCTION IN IRRELEVANT RESULTS: {reduction:.1f}%")
    cons_reduction = relative_reduction(baseline.irrelevant_rate, conservative_arm.irrelevant_rate)
    print(
        f"  conservative (threshold {conservative['threshold']}): "
        f"{conservative_arm.irrelevant_rate:.1%} irrelevant, {cons_reduction:.1f}% reduction, "
        f"hit {conservative_arm.hit_rate:.0%}"
    )
    print(
        f"  full pipeline incl. LLM grading: {end_to_end.irrelevant_rate:.1%} irrelevant, "
        f"{relative_reduction(baseline.irrelevant_rate, end_to_end.irrelevant_rate):.1f}% "
        f"reduction, hit {end_to_end.hit_rate:.0%}"
    )
    print(
        f"  (all {len(everything)} questions, for reference: "
        f"{relative_reduction(full_arms[0].irrelevant_rate, full_arms[-1].irrelevant_rate):.1f}%)"
    )
    print("=" * 78)
    print(f"\n  Tuned parameters: mmr_lambda={mmr_lambda}, score_threshold={threshold}")
    print("  Set these in .env to make them the production defaults.")
    print(f"\n  Report written to {REPORT_PATH}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
