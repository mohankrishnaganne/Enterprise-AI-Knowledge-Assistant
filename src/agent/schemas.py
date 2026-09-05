"""Structured output schemas for the LLM-driven nodes.

Each node that asks the model for a decision (rather than prose) binds one of these via
``with_structured_output``. Free-text parsing of routing or grading decisions is the
single most common source of flakiness in agent pipelines; a schema turns a parse failure
into a validation error the node can handle explicitly.

Field descriptions are not documentation -- they are sent to the model as part of the
tool schema and materially affect output quality, so they are written for the model to
read.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from src.config import CATEGORIES


class RouteDecision(BaseModel):
    """How the agent should handle an incoming question."""

    intent: Literal["knowledge", "chitchat", "out_of_scope"] = Field(
        description=(
            "'knowledge' if answering requires looking something up in the company "
            "knowledge base. 'chitchat' for greetings, thanks, or questions about the "
            "assistant itself. 'out_of_scope' for requests that are neither, such as "
            "general world knowledge, coding help, or anything unrelated to the company."
        )
    )
    category: Literal["technical", "operational", "business", "unknown"] = Field(
        description=(
            "Which part of the knowledge base most likely holds the answer. "
            "'technical' = APIs, architecture, deployment, database schemas, SDKs. "
            "'operational' = HR policy, onboarding, incident process, on-call, security "
            "compliance, expenses, remote work. "
            "'business' = pricing, financial results, competitors, roadmap, partners, "
            "support SLAs. "
            "Use 'unknown' if the question spans several areas or you are not confident; "
            "an incorrect category hides the answer entirely, so prefer 'unknown' over a "
            "guess."
        )
    )
    needs_decomposition: bool = Field(
        description=(
            "True if the question contains two or more distinct information needs that "
            "would be better searched separately, for example 'what is X and how does it "
            "compare to Y'. False for a single focused question."
        )
    )
    reason: str = Field(
        description="One short sentence explaining the classification.",
        max_length=300,
    )

    @property
    def category_filter(self) -> str | None:
        """The category as a retrieval filter, or ``None`` when unknown."""
        return self.category if self.category in CATEGORIES else None


class SubQueries(BaseModel):
    """A compound question broken into independently searchable parts."""

    subqueries: list[str] = Field(
        description=(
            "Between 1 and 3 self-contained search queries. Each must make sense on its "
            "own without the others, so resolve any pronouns and repeat the subject. "
            "If the original question is already focused, return it unchanged as the "
            "single element."
        ),
        min_length=1,
        max_length=3,
    )


class DocumentGrade(BaseModel):
    """The relevance verdict for one retrieved chunk."""

    index: int = Field(description="The 1-based number of the document being graded.")
    relevant: bool = Field(
        description=(
            "True only if this document contains information that helps answer the "
            "question. Being about the same general topic is not enough -- it must "
            "contain part of the actual answer."
        )
    )
    reason: str = Field(
        description="A brief justification, at most fifteen words.",
        max_length=200,
    )


class GradingResult(BaseModel):
    """Verdicts for a whole batch of retrieved chunks.

    Grading is batched into one call rather than one call per chunk. With six chunks
    that is the difference between 1 and 6 requests against the Groq free tier's
    per-minute limit, and it also lets the model compare candidates against each other.
    """

    grades: list[DocumentGrade] = Field(
        description="One entry per document supplied, in the same order."
    )


class RewrittenQuery(BaseModel):
    """A reformulated search query after retrieval came back irrelevant."""

    query: str = Field(
        description=(
            "A rewritten search query. Do not simply rephrase: change the retrieval "
            "strategy. Use the vocabulary the source documents would use rather than the "
            "user's, broaden an over-specific question, or narrow a vague one."
        )
    )
    strategy: str = Field(
        description="A few words naming what you changed, e.g. 'broadened; used policy terminology'.",
        max_length=200,
    )
