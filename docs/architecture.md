# System Architecture

Three independent subsystems: **offline ingestion**, **online agent + serving**, and
**offline evaluation**. They share only `src/config.py` and the Pinecone index.

## 1. Ingestion pipeline (offline, run on corpus change)

```
data/raw/{technical,operational,business}/*.md, *.pdf
        |
        v
[src/ingestion/loaders.py]
        Walks the corpus tree. Markdown -> TextLoader, PDF -> PyPDFLoader.
        Emits LangChain Documents with the file path preserved.
        |
        v
[src/ingestion/chunker.py]
        RecursiveCharacterTextSplitter with markdown-aware separators
        ("\n## ", "\n### ", "\n\n", "\n", " ") so splits land on section
        boundaries instead of mid-sentence.
        OPTIMIZED: chunk_size=800, overlap=120
        BASELINE : fixed 512-char split, overlap=0   <-- used only by the benchmark
        |
        v
[src/ingestion/metadata.py]
        Attaches per-chunk metadata:
          source      relative file path                    -> shown in citations
          category    technical|operational|business         -> Pinecone metadata FILTER
          doc_title   H1 of the document
          section     nearest preceding H2/H3                -> sharper citations
          chunk_id    deterministic sha1(source + index)     -> idempotent re-ingest
        |
        v
[src/retrieval/embedder.py]
        HuggingFaceEmbeddings("BAAI/bge-small-en-v1.5"), 384-dim, runs LOCALLY.
        Cached as a module singleton so the model loads once per process.
        |
        v
[src/retrieval/vector_store.py]
        Creates the Pinecone serverless index if absent (cosine, dim=384),
        then upserts in batches. Namespaces:
          v1        optimized chunks (serves the app)
          baseline  naive chunks     (serves the A/B benchmark only)
```

Deterministic `chunk_id`s mean re-running ingestion overwrites rather than duplicates.

## 2. Query-time agent (LangGraph)

State (`src/agent/state.py`) threads through every node and accumulates a `trace`
of visited nodes, which the UI renders.

```
                          +---------+
                          |  START  |
                          +----+----+
                               |
                               v
                    +----------------------+
                    |     route_query      |   structured output (Pydantic):
                    |  Groq 8B, temp=0     |     intent: knowledge|chitchat|out_of_scope
                    |                      |     category_filter: technical|operational|
                    |                      |                      business|null
                    |                      |     needs_decomposition: bool
                    +---+--------------+---+
        intent != knowledge |          | intent == knowledge
                            v          v
                +---------------+   +------------------------+
                | direct_answer |   |    decompose_query     |
                |   (no RAG)    |   | splits compound asks   |
                +-------+-------+   | into <= MAX_SUBQUERIES |
                        |           +-----------+------------+
                        |                       |
                        |                       v
                        |           +------------------------+
                        |           |        retrieve        | <---------+
                        |           | Pinecone similarity    |           |
                        |           |   top_k=6, fetch_k=20  |           |
                        |           | + metadata filter      |           |
                        |           | + MMR (lambda=0.5)     |           |
                        |           | + score threshold      |           |
                        |           +-----------+------------+           |
                        |                       |                        |
                        |                       v                        |
                        |           +------------------------+           |
                        |           |    grade_documents     |           |
                        |           | LLM-as-judge, Groq 8B  |           |
                        |           | one batched call ->    |           |
                        |           | [{id, relevant, why}]  |           |
                        |           +-----------+------------+           |
                        |                       |                        |
                        |                  < decide_next >               |
                        |          +------------+------------+           |
                        |          |            |            |           |
                        |   relevant >= 1  relevant == 0  relevant == 0  |
                        |          |     & rewrites<MAX   & rewrites==MAX|
                        |          v            v            v           |
                        |  +----------------+ +---------+ +----------+   |
                        |  |validate_sources| |rewrite_ | | fallback |   |
                        |  | dedupe by      | | query   | +----+-----+   |
                        |  | chunk_id, rank | | Groq 8B |      |         |
                        |  | by score, cap  | | reframes|------+---------+
                        |  | at top 4       | | the ask |      |
                        |  +-------+--------+ +---------+      |
                        |          |                           |
                        |          v                           |
                        |  +---------------+                   |
                        |  |   generate    |                   |
                        |  | Groq 70B      |                   |
                        |  | grounded, with|                   |
                        |  | [1][2] cites  |                   |
                        |  +-------+-------+                   |
                        |          |                           |
                        +----------+---------------------------+
                                   |
                                   v
                                +-----+
                                | END |
                                +-----+
```

**Loop guard:** `rewrite_query` increments `state["rewrites"]`. `decide_next` routes to
`fallback` once it hits `MAX_QUERY_REWRITES`, so the graph cannot cycle indefinitely.

**Rate-limit design:** grading is a single batched call over all retrieved chunks (not one
call per chunk), and routing, grading and rewriting all use the 8B model. Only the final
`generate` step uses the 70B model. A full request costs ~4 Groq calls worst case, which
keeps it well inside the free tier's ~30 requests/minute.

## 3. Serving

```
  Browser
     |
     v
  ui/app.py (Streamlit :8501)
     |  POST /chat  {"question", "session_id"}
     v
  api/main.py (FastAPI :8000)
     |  graph compiled ONCE in the lifespan handler, reused per request
     v
  src/agent/graph.py  ->  {answer, citations[], trace[], latency_ms}
```

The `trace` array is surfaced in the Streamlit "Agent reasoning" expander, so the retry loop
is visible rather than implied.

## 4. Evaluation (offline)

```
data/eval/golden_dataset.json   (question, ground_truth, relevant_chunk_ids)
        |
        +--> scripts/run_ragas_eval.py
        |       Runs each question through the full graph, then scores with RAGAS:
        |         faithfulness, answer_relevancy, context_precision, context_recall
        |       Judge LLM = Groq (free), embeddings = local HF (free).
        |       -> reports/ragas_scores.md
        |
        +--> scripts/benchmark_retrieval.py
                BASELINE : namespace=baseline, 512-char chunks, no overlap,
                           no metadata filter, plain similarity, k=5, no grading
                OPTIMIZED: namespace=v1, 800/120 chunks, router metadata filter,
                           MMR, score threshold, LLM grading
                metric   : irrelevant-rate = (retrieved not in relevant) / retrieved,
                           averaged over all golden queries
                -> reports/retrieval_benchmark.md (baseline -> optimized, relative delta)
```

The benchmark is the evidence behind the retrieval-optimization claim. The number it prints
is whatever the measurement yields; it is not hardcoded anywhere.
