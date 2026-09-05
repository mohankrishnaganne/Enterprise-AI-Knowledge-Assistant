"""Ingest the corpus into Pinecone.

python scripts/run_ingestion.py              # optimized arm only (what the app uses)
python scripts/run_ingestion.py --both       # optimized + baseline (needed by the benchmark)
python scripts/run_ingestion.py --dry-run    # chunk and report, touch nothing remote
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import RAW_DATA_DIR  # noqa: E402
from src.ingestion.chunker import Strategy, chunk_documents, get_config  # noqa: E402
from src.ingestion.loaders import load_corpus  # noqa: E402
from src.ingestion.metadata import enrich_chunks  # noqa: E402
from src.ingestion.pipeline import ingest, ingest_both_arms  # noqa: E402
from src.logging_conf import get_logger  # noqa: E402

log = get_logger(__name__)


def _dry_run(strategies: list[Strategy]) -> int:
    """Chunk locally and print statistics without embedding or contacting Pinecone."""
    documents = load_corpus(RAW_DATA_DIR)

    print(f"\nLoaded {len(documents)} documents from {RAW_DATA_DIR}\n")

    for strategy in strategies:
        config = get_config(strategy)
        chunks = chunk_documents(documents, strategy)
        enrich_chunks(chunks, documents, add_context_header=strategy is Strategy.OPTIMIZED)

        by_category: dict[str, int] = {}
        for chunk in chunks:
            key = chunk.metadata["category"]
            by_category[key] = by_category.get(key, 0) + 1

        sizes = [c.metadata["char_count"] for c in chunks]
        with_section = sum(1 for c in chunks if c.metadata["section"])

        print(f"--- {config.describe()}")
        print(f"    chunks           : {len(chunks)}")
        print(
            f"    chars per chunk  : mean {round(sum(sizes) / len(sizes))}, "
            f"min {min(sizes)}, max {max(sizes)}"
        )
        print(
            f"    with section meta: {with_section}/{len(chunks)} "
            f"({100 * with_section / len(chunks):.0f}%)"
        )
        print(f"    by category      : {dict(sorted(by_category.items()))}")

        sample = chunks[len(chunks) // 3]
        print(f"    sample chunk_id  : {sample.metadata['chunk_id']}")
        print(
            f"    sample source    : {sample.metadata['source']} > "
            f"{sample.metadata['section'] or '(no section)'}"
        )
        print(f"    sample text      : {sample.page_content[:160].replace(chr(10), ' ')}...\n")

    print("Dry run only -- nothing was embedded or upserted.\n")
    return 0


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Ingest the corpus into Pinecone.")
    parser.add_argument(
        "--both",
        action="store_true",
        help="Ingest the baseline arm as well; required before `make bench`.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Chunk and report statistics without embedding or upserting.",
    )
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="Upsert without clearing the namespace first (incremental update).",
    )
    args = parser.parse_args()

    strategies = [Strategy.OPTIMIZED] + ([Strategy.BASELINE] if args.both else [])

    if args.dry_run:
        return _dry_run(strategies)

    if args.both:
        results = ingest_both_arms()
    else:
        results = [ingest(strategy=Strategy.OPTIMIZED, reset=not args.no_reset)]

    print()
    for result in results:
        print("  " + result.summary())

    # Confirm what actually landed remotely, rather than trusting the local count.
    from src.retrieval.vector_store import describe_stats

    stats = describe_stats()
    print(
        f"\n  Pinecone index now holds {stats['total_vectors']} vectors "
        f"across namespaces {stats['namespaces']}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
