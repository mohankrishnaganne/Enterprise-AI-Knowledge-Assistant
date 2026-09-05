"""Request and response models for the HTTP API.

These are the public contract. They deliberately expose more than the answer text:
``trace`` and ``rewrites`` let a caller see *how* the answer was reached, and
``insufficient_evidence`` lets a caller distinguish "the assistant declined" from "the
assistant answered", which a plain string cannot express.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """A question for the assistant."""

    question: str = Field(
        min_length=1,
        max_length=2000,
        description="The user's question.",
        examples=["How much PTO do I get, and how many days can I carry over?"],
    )
    session_id: str | None = Field(
        default=None,
        max_length=128,
        description="Opaque client-side conversation id. Echoed back; used for log correlation.",
    )


class Citation(BaseModel):
    """One source passage behind an answer.

    ``n`` matches the bracketed marker in the answer text, so a client can turn ``[2]``
    into a link to the second citation.
    """

    n: int = Field(description="Citation number, matching the [n] marker in the answer.")
    source: str = Field(description="Document path relative to the corpus root.")
    section: str = Field(default="", description="Section heading within the document.")
    doc_title: str = Field(default="", description="Title of the source document.")
    category: str = Field(default="", description="technical, operational or business.")
    score: float = Field(description="Cosine similarity of the chunk to the search query.")
    chunk_id: str = Field(description="Stable chunk identifier.")
    snippet: str = Field(description="Leading text of the cited passage.")


class TraceStep(BaseModel):
    """One node the agent executed."""

    node: str = Field(description="Node name, e.g. 'retrieve' or 'rewrite_query'.")
    detail: str = Field(description="What the node did.")
    elapsed_ms: int = Field(description="Wall-clock time spent in the node.")


class ChatResponse(BaseModel):
    """The assistant's answer plus how it got there."""

    question: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    trace: list[TraceStep] = Field(default_factory=list)
    path: str = Field(
        default="",
        description="Nodes visited, arrow-separated.",
        examples=["route_query -> retrieve -> grade_documents -> rewrite_query -> retrieve"],
    )
    intent: Literal["knowledge", "chitchat", "out_of_scope"] = "knowledge"
    category_filter: str | None = Field(
        default=None, description="Metadata filter the router chose, if any."
    )
    rewrites: int = Field(default=0, description="Self-correction attempts made.")
    insufficient_evidence: bool = Field(
        default=False,
        description="True when the agent declined to answer for lack of grounded evidence.",
    )
    latency_ms: int = 0
    session_id: str | None = None


class HealthResponse(BaseModel):
    """Liveness: the process is up. Says nothing about dependencies."""

    status: Literal["ok"] = "ok"
    version: str


class ReadinessComponent(BaseModel):
    """The state of one external dependency."""

    name: str
    ready: bool
    detail: str = ""


class ReadinessResponse(BaseModel):
    """Readiness: every dependency needed to serve a request is usable."""

    ready: bool
    components: list[ReadinessComponent]


class ErrorResponse(BaseModel):
    """A structured error, so clients never have to parse a message string."""

    error: str
    detail: str = ""
