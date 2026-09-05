# RAGAS Evaluation

_Generated 2026-09-05 03:16 UTC by `scripts/run_ragas_eval.py`. Regenerate with `make eval`._

## Scores

| Metric | Score | What it measures |
| --- | ---: | --- |
| `faithfulness` | **0.950** | Fraction of claims in the answer that are supported by the retrieved context. This is the hallucination measure: 1.0 means every claim is grounded. |
| `answer_relevancy` | **0.881** | Whether the answer addresses the question asked. Computed by generating questions from the answer and comparing them to the original in embedding space. |
| `context_precision` | **0.900** | Whether the context that mattered was ranked highly, judged by an LLM against the reference answer. |
| `context_recall` | **1.000** | Whether the retrieved context covers the reference answer. Low values mean the retriever missed something the answer needed. |

Judge model: `openai/gpt-oss-120b` (Groq). Embeddings: `BAAI/bge-small-en-v1.5` (local). Both free-tier, so this evaluation costs nothing to reproduce.

## What was evaluated

Each of the 5 questions was run through the **full LangGraph agent** — routing, decomposition, retrieval, LLM grading, and any query rewrites — and the answer it actually produced was scored. Evaluating a bare retrieve-and-generate chain would measure a system that is not the one being shipped.

| Question | Path | Rewrites | Sources | Latency |
| --- | --- | ---: | ---: | ---: |
| `q01` How many API requests per minute does the Gr | decompose_query → retrieve → grade_documents → validate_sour | 0 | 1 | 45.9s |
| `q02` How long are ACME access tokens valid, and h | decompose_query → retrieve → grade_documents → validate_sour | 0 | 1 | 7.8s |
| `q03` What has to be true before I can deploy to p | decompose_query → retrieve → grade_documents → validate_sour | 0 | 2 | 8.5s |
| `q04` Why does it take about 30 seconds for ingest | decompose_query → retrieve → grade_documents → validate_sour | 0 | 2 | 14.2s |
| `q05` What produces the 409 DATASET_EXISTS error a | decompose_query → retrieve → grade_documents → validate_sour | 0 | 1 | 15.6s |

## Per-question scores

| Question | `faithfulness` | `answer_relevancy` | `context_precision` | `context_recall` |
| --- | ---: | ---: | ---: | ---: |
| How many API requests per minute does the Growth pla | 1.000 | 1.000 | 1.000 | 1.000 |
| How long are ACME access tokens valid, and how do re | 1.000 | 0.961 | 1.000 | 1.000 |
| What has to be true before I can deploy to productio | — | 0.825 | 1.000 | 1.000 |
| Why does it take about 30 seconds for ingested recor | 0.800 | 0.898 | 0.500 | 1.000 |
| What produces the 409 DATASET_EXISTS error at the da | 1.000 | 0.721 | 1.000 | 1.000 |

## Interpretation and limitations

- **Faithfulness is the metric that matters most here.** The whole premise of this system is that answers are grounded in retrieved passages; a high faithfulness score is evidence that the citation discipline in the generation prompt actually holds.
- **Context is taken from the citations the agent returned**, i.e. after LLM grading and source validation. That is the context the answer was genuinely written from, so it is the honest input to these metrics.
- **Questions the agent declined are excluded.** A refusal has no retrieved context, and faithfulness against empty context is undefined rather than zero. Scoring them as 0 would understate the system for behaving correctly.
- **Small sample (5 questions).** These scores show a direction, not a confidence interval. The judge is also an LLM, so scores vary a little between runs even at temperature 0.
- The retrieval side is measured separately and more rigorously in [`retrieval_benchmark.md`](retrieval_benchmark.md), which uses a deterministic relevance rule and a held-out test split rather than LLM judgement.

_Run took 446s._
