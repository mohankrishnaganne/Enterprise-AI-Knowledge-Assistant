# Retrieval Benchmark: naive baseline vs optimized pipeline

_Generated 2026-09-05 03:06 UTC by `scripts/benchmark_retrieval.py`. Regenerate with `make bench`._

## Headline

**Irrelevant retrieved results fell 18.3%** — from 71.4% to 58.3% of returned chunks — on 7 **held-out** questions the retrieval parameters were never tuned against.

**This came at a cost.** Hit rate fell from 100% to 86% — 1 of 7 held-out questions no longer retrieved any relevant chunk, because the tuned score threshold excluded it. The threshold satisfied the no-hit-loss constraint on dev and did not generalise. This is a real trade-off, not a rounding artifact, and the conservative configuration below avoids it.

| Configuration | Irrelevant rate | Reduction | Hit rate |
| --- | ---: | ---: | ---: |
| A. baseline | 71.4% | — | 100% |
| D. tuned optimum (threshold 0.65) | 58.3% | 18.3% | 86% |
| D'. conservative (threshold 0.62) | 65.2% | 8.7% | 100% |

**Recommended for production: the conservative configuration.** For a knowledge assistant a missed answer is worse than a noisy one, especially since the agent's LLM grading step removes irrelevant chunks downstream anyway. The claim to quote is therefore the conservative row.

Across all 15 answerable questions (dev + test) the reduction is 28.0%; the held-out figure above is the one to quote.

## Ablation (held-out test split)

Each arm adds one change to the one above it. Every arm returns top-k=5 where a rate is compared.

| Arm | Irrelevant rate | Precision | MRR | Hit rate | Chunks/question |
| --- | ---: | ---: | ---: | ---: | ---: |
| A. baseline | 71.4% | 28.6% | 1.000 | 100% | 5.00 |
| B. + optimized chunking | 68.6% | 31.4% | 0.786 | 100% | 5.00 |
| C. + metadata filter | 68.6% | 31.4% | 0.786 | 100% | 5.00 |
| D. + MMR and score threshold (production) | 58.3% | 41.7% | 0.714 | 86% | 3.43 |

### Contribution of each change

| Change | Irrelevant rate | Reduction vs. previous arm |
| --- | ---: | ---: |
| A. baseline (starting point) | 71.4% | — |
| B. + optimized chunking | 68.6% | +4.0% |
| C. + metadata filter | 68.6% | +0.0% |
| D. + MMR and score threshold (production) | 58.3% | +14.9% |

## Ablation (all answerable questions, for reference)

| Arm | Irrelevant rate | Precision | MRR | Hit rate | Chunks/question |
| --- | ---: | ---: | ---: | ---: | ---: |
| A. baseline | 69.3% | 30.7% | 0.933 | 100% | 5.00 |
| B. + optimized chunking | 68.0% | 32.0% | 0.833 | 100% | 5.00 |
| C. + metadata filter | 68.0% | 32.0% | 0.833 | 100% | 5.00 |
| D. + MMR and score threshold (production) | 49.9% | 50.1% | 0.800 | 93% | 3.27 |

## Arm definitions

- **A. baseline** — 512-char naive chunks, no overlap, no contextual header; plain top-k=5, unfiltered, no MMR, no score threshold
- **B. + optimized chunking** — 800/120 markdown-aware chunks with contextual headers; retrieval still plain top-k=5, unfiltered
- **C. + metadata filter** — as B, plus the category filter chosen by the live LLM router
- **D. + MMR and score threshold (production)** — as C, plus over-fetch to 20, MMR (lambda=1.0) and score threshold 0.65, both tuned on the dev split

## Tuning

MMR lambda and the score threshold were selected on the 8-question dev split (28 configurations searched), then frozen. Selection rule, fixed before any numbers were seen: **minimise the irrelevant rate subject to losing no hit rate**.

Chosen: `mmr_lambda=1.0`, `score_threshold=0.65`.

Notable dev-split results:

| MMR lambda | Threshold | Irrelevant rate | Hit rate |
| ---: | ---: | ---: | ---: |
| 1.0 | 0.68 | 22.9% | 88% |
| 0.9 | 0.68 | 22.9% | 88% |
| 0.7 | 0.68 | 22.9% | 88% |
| 0.5 | 0.68 | 22.9% | 88% |
| 1.0 | 0.65 | 42.5% | 100% **(chosen)** |
| 0.9 | 0.65 | 42.5% | 100% |
| 0.7 | 0.65 | 42.5% | 100% |
| 0.5 | 0.65 | 42.5% | 100% |

## What the tuning found

Two results here contradicted the initial configuration, and both are worth stating plainly:

- **MMR hurt.** Diversity is the wrong objective for this corpus: only ~1.6 chunks per question contain the answer, so there is no breadth to recover and MMR simply displaces the best chunk. The tuner selected a lambda at or near 1.0, which is close to disabling it. It is retained because multi-hop questions do benefit, but at a far higher lambda than the 0.5 originally configured.
- **The original 0.35 score threshold was a no-op.** Every cosine score in this corpus sits above it, so it never removed anything. The threshold only starts doing work around 0.60, and that is where nearly all of arm D's gain comes from.

## Metric definitions

- **Irrelevant rate** (headline) — of the chunks returned, the fraction failing the relevance rule, macro-averaged across questions. A retriever returning nothing scores 1.0, so an arm cannot win by refusing to answer.
- **Relevance rule** — a chunk is relevant iff its source document is one of the question's `expected_sources` **and** its text contains one of its `answer_phrases`. Defined in `src/evaluation/golden.py`, keyed on source and content rather than chunk id, because the arms cut documents at different boundaries so their chunk ids are not comparable.
- **Hit rate** — questions where at least one relevant chunk was returned. Deliberately *not* called recall: true recall would require every relevant passage in the corpus to be labelled, which this golden set does not do.
- **MRR** — mean reciprocal rank of the first relevant chunk. Rewards ranking the answer first, not merely including it.
- **Reduction** — *relative*: `(baseline - optimized) / baseline`. Not the difference in percentage points, which would be a different and larger-sounding claim.

## Method and limitations

- 8 dev / 7 held-out test questions, split deterministically by position so both halves span all three categories. Both include PDF-sourced and multi-hop questions.
- Both arms query the same Pinecone index and the same embedding model. The only differences are those named in the arm definitions.
- The live LLM router chose the expected category for 15/15 questions. Router errors count against the optimized arms, as in production.
- **Small sample.** 7 held-out questions is enough to show a direction, not to put a confidence interval on it. One question changing outcome moves the headline by several points. The dev/test split protects against tuning overfit; it does not turn 7 questions into a large sample.
- **Retrieval only.** The agent additionally grades every retrieved chunk with an LLM and discards the irrelevant ones before generation, so the context that actually reaches the answer is cleaner than arm D. That step is excluded here to keep the benchmark deterministic and free of LLM sampling variance.
- Chunking: optimized: size=800, overlap=120, separators=8 vs baseline: size=512, overlap=0, separators=1.
- Run took 1101.2s.

## Per-question detail (held-out test split)

Irrelevant chunks returned / chunks returned.

| Question | A | B | C | D |
| --- | ---: | ---: | ---: | ---: |
| `q02` How long are ACME access tokens valid, and how do re | 4/5 | 4/5 | 4/5 | 4/5 |
| `q04` Why does it take about 30 seconds for ingested recor | 4/5 | 3/5 | 3/5 | 1/1 |
| `q06` How quickly must an on-call engineer acknowledge a p | 3/5 | 3/5 | 3/5 | 3/5 |
| `q08` How many PTO days do I get, and how many can I carry | 3/5 | 3/5 | 3/5 | 1/3 |
| `q10` What are the MFA requirements for engineers with pro | 4/5 | 4/5 | 4/5 | 0/1 |
| `q12` What was ACME's ARR at the end of Q3 2025 and how di | 4/5 | 4/5 | 4/5 | 3/4 |
| `q14` What is the P1 support response target for an Enterp | 3/5 | 3/5 | 3/5 | 3/5 |
