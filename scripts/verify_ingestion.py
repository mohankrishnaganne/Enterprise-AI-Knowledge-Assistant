"""Verify that what landed in Pinecone is actually retrievable.

Ingestion reporting a vector count proves only that an upsert succeeded. This script
checks the properties that matter downstream:

1. Every category is represented and metadata filtering actually restricts results.
2. Golden questions retrieve at least one chunk that satisfies the relevance rule --
   if this fails, the corpus and the golden set have drifted apart and every number the
   Phase 5 benchmark reports would be meaningless.

Run after ``scripts/run_ingestion.py``::

    python scripts/verify_ingestion.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import CATEGORIES, settings  # noqa: E402
from src.evaluation.golden import answerable, validate  # noqa: E402
from src.logging_conf import get_logger  # noqa: E402
from src.retrieval.embedder import embed_query  # noqa: E402
from src.retrieval.vector_store import describe_stats, ensure_index, query  # noqa: E402

log = get_logger(__name__)


def main() -> int:
    """Run the verification checks and report a pass/fail summary."""
    failures: list[str] = []
    index = ensure_index()

    # --- Index state ---------------------------------------------------------
    stats = describe_stats(index=index)
    print(
        f"\nIndex '{settings.pinecone_index_name}': {stats['total_vectors']} vectors, "
        f"dim={stats['dimension']}, namespaces={stats['namespaces']}\n"
    )

    if stats["namespaces"].get(settings.pinecone_namespace, 0) == 0:
        failures.append(f"namespace {settings.pinecone_namespace!r} is empty; run run_ingestion.py")

    # --- Golden set integrity ------------------------------------------------
    problems = validate()
    if problems:
        failures.extend(f"golden set: {p}" for p in problems)

    # --- Metadata filtering --------------------------------------------------
    print("Metadata filter check (a filtered query must return only its category):")
    probe = embed_query("What are the rules and limits that apply here?")
    for category in CATEGORIES:
        matches = query(probe, top_k=5, metadata_filter={"category": {"$eq": category}})
        leaked = [m for m in matches if m["metadata"].get("category") != category]
        status = "ok" if matches and not leaked else "FAIL"
        print(f"  {category:12} {len(matches)} hits  {status}")
        if not matches:
            failures.append(f"no chunks retrievable for category {category!r}")
        if leaked:
            failures.append(
                f"filter leak: {category!r} query returned {len(leaked)} foreign chunks"
            )

    # --- Golden question retrieval -------------------------------------------
    print("\nGolden question retrieval (unfiltered, top-6):")
    questions = answerable()
    misses = 0

    for question in questions:
        vector = embed_query(question.question)
        matches = query(vector, top_k=settings.retrieval_top_k)
        hits = [
            m
            for m in matches
            if question.is_relevant(m["metadata"].get("source", ""), m["metadata"].get("text", ""))
        ]
        top_score = matches[0]["score"] if matches else 0.0
        flag = "ok  " if hits else "MISS"
        print(
            f"  {question.id}  {flag} {len(hits)}/{len(matches)} relevant  "
            f"top={top_score:.3f}  {question.question[:58]}"
        )
        if not hits:
            misses += 1
            top_sources = ", ".join(m["metadata"].get("source", "?") for m in matches[:3])
            print(f"        expected {list(question.expected_sources)}; got {top_sources}")

    recall = (len(questions) - misses) / len(questions)
    print(
        f"\nAt least one relevant chunk retrieved for {len(questions) - misses}/{len(questions)} "
        f"questions ({recall:.0%})."
    )

    # A golden question that retrieves nothing relevant makes the benchmark unable to
    # measure anything on that question, so treat a low rate as a hard failure.
    if recall < 0.8:
        failures.append(f"only {recall:.0%} of golden questions retrieved a relevant chunk")

    print()
    if failures:
        print("FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("All ingestion checks passed.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
