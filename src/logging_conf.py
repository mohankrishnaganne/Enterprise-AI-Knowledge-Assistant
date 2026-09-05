"""Structured logging setup.

Console-friendly colourised output when attached to a TTY (local development), plain
JSON otherwise (containers, CI, Hugging Face Spaces) so logs stay machine-parseable in
deployment. Call :func:`configure_logging` once at process start.
"""

from __future__ import annotations

import logging
import sys

import structlog

from src.config import settings

_CONFIGURED = False


def configure_logging(level: str | None = None) -> None:
    """Configure structlog + stdlib logging. Safe to call more than once."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    log_level = getattr(logging, (level or settings.log_level).upper(), logging.INFO)

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=log_level)

    # Third-party libraries are chatty at INFO; keep our own output readable.
    for noisy in ("httpx", "urllib3", "sentence_transformers", "pinecone"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer = (
        structlog.dev.ConsoleRenderer()
        if sys.stdout.isatty()
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    _CONFIGURED = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound logger, configuring logging on first use."""
    configure_logging()
    return structlog.get_logger(name)
