"""RAGAS evaluation harness.

Answers the question the retrieval benchmark cannot: given the context the agent
actually assembled, is the *answer* faithful to it and relevant to the question?

Metrics:

``faithfulness``
    Fraction of claims in the answer that are supported by the retrieved context. This
    is the hallucination measure, and the one that matters most for a system whose whole
    premise is grounded answers.
``answer_relevancy``
    Whether the answer addresses the question asked, rather than something adjacent.
``context_precision``
    Whether the retrieved context that mattered was ranked highly. Complements the
    retrieval benchmark's own precision figure with an LLM's judgement rather than a
    string-matching rule.
``context_recall``
    Whether the retrieved context covers the reference answer.

Both the judge LLM and the embeddings are the project's own free-tier providers -- Groq
and local HuggingFace -- so the evaluation costs nothing to run.

**Compatibility note.** ragas 0.4.3 imports ``langchain_community.chat_models.vertexai``
at module load, which ``langchain-community`` 0.4.x removed when it was sunset. That is a
hard import error unrelated to anything this project uses, so :func:`_install_compat_shim`
registers a stub for it before ragas is imported. Without the shim ragas cannot be
imported at all alongside LangChain 1.x.
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from typing import Any

from src.config import settings
from src.logging_conf import get_logger

log = get_logger(__name__)

# The metrics requested, in report order.
METRIC_NAMES = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")


def _install_compat_shim() -> None:
    """Register the module ragas imports but langchain-community no longer ships.

    ragas only needs the symbol to exist for provider dispatch; this project never uses
    Vertex AI, so a stub class is sufficient and nothing silently degrades.
    """
    name = "langchain_community.chat_models.vertexai"
    if name in sys.modules:
        return

    module = types.ModuleType(name)
    module.ChatVertexAI = type("ChatVertexAI", (), {})
    sys.modules[name] = module
    log.debug("installed_ragas_compat_shim", module=name)


@dataclass
class RagasScores:
    """Aggregated RAGAS results."""

    scores: dict[str, float] = field(default_factory=dict)
    per_sample: list[dict[str, Any]] = field(default_factory=list)
    judge_model: str = ""
    failures: list[str] = field(default_factory=list)

    def get(self, metric: str) -> float | None:
        """Return one metric's score, or None if it could not be computed."""
        value = self.scores.get(metric)
        return None if value is None else float(value)


def build_judge():
    """Return the Groq judge, wrapped as an instructor-style ragas LLM.

    ragas 0.4 metrics require an ``InstructorBaseRagasLLM``, not the LangChain wrapper
    earlier versions took. Groq exposes an OpenAI-compatible endpoint, so the OpenAI
    client pointed at Groq's base URL satisfies ragas without pulling in a second
    provider.

    The client must be **async**: ragas metrics call ``agenerate``, which raises on a
    synchronous client.

    The strong model judges. Faithfulness decomposes an answer into claims and checks
    each against the context, which the small model does poorly.
    """
    from openai import AsyncOpenAI
    from ragas.llms import llm_factory

    client = AsyncOpenAI(api_key=settings.require_groq(), base_url="https://api.groq.com/openai/v1")
    return llm_factory(settings.groq_model_strong, provider="openai", client=client)


def build_judge_embeddings():
    """Return the local embedding model in ragas' own HuggingFace wrapper.

    ``answer_relevancy`` works by generating questions from the answer and comparing them
    to the original in embedding space, so it needs embeddings. Using the same model the
    retriever uses keeps the evaluation free, offline and consistent with the system
    being measured.
    """
    from ragas.embeddings import HuggingFaceEmbeddings as RagasHuggingFaceEmbeddings

    return RagasHuggingFaceEmbeddings(model=settings.embedding_model)


def _score_value(result: Any) -> float | None:
    """Unwrap a ragas ``MetricResult`` into a plain float."""
    value = getattr(result, "value", result)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def _score_sample(sample: dict, judge, embeddings) -> dict[str, float | None]:
    """Score one sample across all four metrics."""
    from ragas.metrics.collections import (
        AnswerRelevancy,
        ContextPrecisionWithReference,
        ContextRecall,
        Faithfulness,
    )

    question = sample["user_input"]
    response = sample["response"]
    contexts = sample["retrieved_contexts"]
    reference = sample["reference"]

    scores: dict[str, float | None] = {}

    # Each metric is scored independently so one failure does not lose the sample.
    # Calls are sequential rather than gathered: Groq's free tier rate-limits hard, and
    # parallel judge calls come back as scattered errors that look like metric failures.
    async def run(name: str, coro):
        try:
            scores[name] = _score_value(await coro)
        except Exception as exc:  # noqa: BLE001
            log.warning("metric_failed", metric=name, question=question[:60], error=str(exc)[:200])
            scores[name] = None

    await run(
        "faithfulness",
        Faithfulness(llm=judge).ascore(
            user_input=question, response=response, retrieved_contexts=contexts
        ),
    )
    await run(
        "answer_relevancy",
        AnswerRelevancy(llm=judge, embeddings=embeddings).ascore(
            user_input=question, response=response
        ),
    )
    await run(
        "context_precision",
        ContextPrecisionWithReference(llm=judge).ascore(
            user_input=question, retrieved_contexts=contexts, reference=reference
        ),
    )
    await run(
        "context_recall",
        ContextRecall(llm=judge).ascore(
            user_input=question, retrieved_contexts=contexts, reference=reference
        ),
    )
    return scores


def evaluate_samples(samples: list[dict[str, Any]]) -> RagasScores:
    """Score agent outputs with RAGAS.

    Args:
        samples: One dict per question with ``user_input``, ``response``,
            ``retrieved_contexts`` (**full** chunk text, not truncated snippets) and
            ``reference``.

    Returns:
        Aggregated and per-sample scores. Failures are captured rather than raised, so a
        single metric erroring does not lose the whole run.
    """
    import asyncio

    _install_compat_shim()

    usable = [s for s in samples if s.get("retrieved_contexts")]
    skipped = len(samples) - len(usable)
    if skipped:
        # A declined answer has no context, and faithfulness against empty context is
        # undefined rather than zero. Excluding is correct; scoring them 0 would
        # penalise the system for correctly refusing to guess.
        log.info("skipping_samples_without_context", skipped=skipped)

    if not usable:
        return RagasScores(failures=["No samples had retrieved context to evaluate."])

    judge = build_judge()
    embeddings = build_judge_embeddings()

    log.info(
        "ragas_evaluation_started",
        samples=len(usable),
        judge=settings.groq_model_strong,
        metrics=list(METRIC_NAMES),
    )

    async def run_all() -> list[dict]:
        results = []
        for sample in usable:
            results.append(await _score_sample(sample, judge, embeddings))
        return results

    try:
        per_sample_scores = asyncio.run(run_all())
    except Exception as exc:  # noqa: BLE001
        log.error("ragas_evaluation_failed", error=str(exc))
        return RagasScores(
            failures=[f"RAGAS evaluation failed: {exc}"],
            judge_model=settings.groq_model_strong,
        )

    failures: list[str] = []
    aggregated: dict[str, float] = {}
    for name in METRIC_NAMES:
        values = [s[name] for s in per_sample_scores if s.get(name) is not None]
        if values:
            aggregated[name] = sum(values) / len(values)
        else:
            failures.append(f"Metric {name!r} produced no scores across any sample.")

    per_sample = [
        {"question": sample["user_input"], **scores}
        for sample, scores in zip(usable, per_sample_scores, strict=True)
    ]

    log.info("ragas_evaluation_complete", **{k: round(v, 4) for k, v in aggregated.items()})
    return RagasScores(
        scores=aggregated,
        per_sample=per_sample,
        judge_model=settings.groq_model_strong,
        failures=failures,
    )
