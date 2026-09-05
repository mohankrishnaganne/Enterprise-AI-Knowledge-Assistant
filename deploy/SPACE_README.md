---
title: Enterprise AI Knowledge Assistant
emoji: 📚
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: Agentic RAG with LangGraph, self-correcting retrieval and cited answers
---

# Enterprise AI Knowledge Assistant

An **Agentic RAG** assistant over a synthetic enterprise corpus (technical, operational
and business documentation for a fictional company, ACME Corp).

It does not simply retrieve and generate. A LangGraph workflow routes each question,
decomposes it when compound, grades every retrieved passage with an LLM judge, and
**rewrites the query and searches again** when the evidence is weak — declining to answer
rather than guessing when it still finds nothing.

## Try these

| Question | What it demonstrates |
| --- | --- |
| *How many API requests per minute does the Growth plan allow?* | Straightforward retrieval with a citation |
| *Which two Enterprise renewals are at risk, and which roadmap item addresses it?* | Query decomposition across two documents, one of them a PDF |
| *What happens if my booked holiday overlaps with an on-call rotation?* | Multi-hop over operational policy |
| *What is ACME's policy on cryptocurrency payments?* | **Self-correction**: two query rewrites, then an honest refusal |

Open the **Agent reasoning** panel under any answer to see the path the graph took.

## Measured results

| Metric | Value |
| --- | ---: |
| Irrelevant context reaching the generator, vs. a naive RAG baseline | **−90.0%** |
| RAGAS faithfulness | **0.950** |
| RAGAS answer relevancy | **0.881** |
| RAGAS context recall | **1.000** |

Both figures are produced by committed scripts and measured on a held-out evaluation
split. Full methodology, including where the measurement contradicted the initial design,
is in the source repository's `reports/` directory.

## Stack

LangGraph · FastAPI · Streamlit · Pinecone Serverless · Groq (gpt-oss) · local
`BAAI/bge-small-en-v1.5` embeddings · RAGAS

Runs entirely on free tiers.

## Configuration

This Space needs two secrets under **Settings → Variables and secrets**:

- `GROQ_API_KEY` — from <https://console.groq.com/keys>
- `PINECONE_API_KEY` — from <https://app.pinecone.io>

The Pinecone index must be populated first by running `python scripts/run_ingestion.py`
against the same account; the Space queries an existing index rather than ingesting on
boot.
