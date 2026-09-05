"""Groq chat model factory.

Two models, chosen to keep a full agent turn inside the Groq free tier's per-minute
request budget and to keep latency low:

``fast``
    Routing, decomposition, grading and rewriting. These are classification tasks with
    structured output where a smaller model performs comparably to a large one, and they
    are where most of the request volume is.

``strong``
    Final answer generation only, where grounding and phrasing quality actually show.

Model ids come from settings so switching providers or models is a ``.env`` edit rather
than a code change. :func:`check_models_available` exists because Groq retires models
periodically -- a stale id otherwise surfaces as an opaque 404 mid-request.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

from langchain_groq import ChatGroq
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential

from src.config import settings
from src.logging_conf import get_logger

log = get_logger(__name__)

Tier = Literal["fast", "strong"]


@lru_cache(maxsize=4)
def get_llm(tier: Tier = "fast", temperature: float | None = None) -> ChatGroq:
    """Return a cached chat model for the given tier.

    Cached so repeated node invocations reuse one HTTP client rather than constructing a
    new one per graph step.
    """
    model = settings.groq_model_strong if tier == "strong" else settings.groq_model_fast

    return ChatGroq(
        model=model,
        api_key=settings.require_groq(),
        temperature=settings.llm_temperature if temperature is None else temperature,
        max_tokens=settings.llm_max_tokens,
        # Groq rate-limits at 429; retry rather than failing a whole graph run. The
        # graph itself makes at most a handful of calls, so this stays bounded.
        max_retries=3,
        timeout=60,
    )


def is_transient_schema_failure(exc: BaseException) -> bool:
    """True for Groq's intermittent ``json_validate_failed`` 400.

    Groq occasionally returns HTTP 400 with ``code: json_validate_failed`` and an *empty*
    ``failed_generation`` -- the model emitted nothing rather than emitting something
    invalid. It is transient: the identical request succeeds on retry (measured at 12/12).

    The SDK will not retry it, because 400 is normally a client error that retrying
    cannot fix. This predicate carves out the one 400 that is genuinely transient, so a
    graph run does not lose a whole node to it. A real schema mismatch would fail every
    attempt and still surface.
    """
    message = str(exc)
    return "json_validate_failed" in message or "Failed to validate JSON" in message


class _RetryingStructuredModel:
    """Wraps a schema-bound model, retrying only transient schema failures."""

    def __init__(self, bound: Any, attempts: int = 3) -> None:
        self._bound = bound
        self._attempts = attempts

    def invoke(self, messages: Any) -> Any:
        """Invoke the model, retrying a transient empty generation."""
        retry = Retrying(
            retry=retry_if_exception(is_transient_schema_failure),
            stop=stop_after_attempt(self._attempts),
            wait=wait_exponential(multiplier=0.5, max=4),
            reraise=True,
            before_sleep=lambda rs: log.warning(
                "retrying_transient_schema_failure", attempt=rs.attempt_number
            ),
        )
        return retry(self._bound.invoke, messages)


def structured(schema: type, tier: Tier = "fast") -> Any:
    """Return a model bound to a Pydantic output schema.

    Uses ``json_schema`` mode rather than the ``function_calling`` default: it constrains
    decoding to the schema, so a malformed decision becomes impossible rather than
    merely unlikely.
    """
    bound = get_llm(tier).with_structured_output(schema, method="json_schema")
    return _RetryingStructuredModel(bound)


def check_models_available() -> list[str]:
    """Verify the configured model ids are actually served by Groq.

    Returns:
        A list of problems; empty means both models are available. Called by the graph
        CLI and the API's readiness check so a retired model id is reported clearly
        instead of failing later as a 404 inside a node.
    """
    import requests

    try:
        response = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {settings.require_groq()}"},
            timeout=15,
        )
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - any failure here is reported, not raised
        return [f"Could not reach the Groq models endpoint: {exc}"]

    available = {model["id"] for model in response.json().get("data", [])}
    problems = []

    for label, model in (
        ("GROQ_MODEL_FAST", settings.groq_model_fast),
        ("GROQ_MODEL_STRONG", settings.groq_model_strong),
    ):
        if model not in available:
            chat_models = sorted(
                m for m in available if not any(x in m for x in ("whisper", "guard", "orpheus"))
            )
            problems.append(
                f"{label}={model!r} is not served by Groq (models are retired periodically). "
                f"Currently available: {', '.join(chat_models)}"
            )

    log.info(
        "groq_models_checked",
        fast=settings.groq_model_fast,
        strong=settings.groq_model_strong,
        problems=len(problems),
    )
    return problems
