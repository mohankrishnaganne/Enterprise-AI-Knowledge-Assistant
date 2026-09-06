# Enterprise AI Knowledge Assistant — developer shortcuts.
# Windows: run these under Git Bash, or copy the command bodies into PowerShell.

.PHONY: help install install-runtime corpus ingest ingest-both verify agent api ui eval bench test lint fmt \
        docker-build docker-run compose deploy clean

help:  ## Show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# --- Setup --------------------------------------------------------------------
install:  ## Install everything (runtime + evaluation + test tooling)
	pip install -r requirements-dev.txt

install-runtime:  ## Install only what is needed to serve requests
	pip install -r requirements.txt

corpus:  ## Generate the synthetic ACME Corp document set into data/raw/
	python scripts/generate_corpus.py

# --- Data ---------------------------------------------------------------------
ingest:  ## Chunk, embed and upsert the corpus into Pinecone (optimized arm)
	python scripts/run_ingestion.py

ingest-both:  ## Ingest optimized + baseline arms; required before `make bench`
	python scripts/run_ingestion.py --both

verify:  ## Check that what landed in Pinecone is actually retrievable
	python scripts/verify_ingestion.py

# --- Running ------------------------------------------------------------------
agent:  ## Drive the agent from the CLI: make agent Q="your question"
	python -m src.agent.graph "$(Q)"

api:  ## Run the FastAPI backend on :8000
	uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

ui:  ## Run the Streamlit frontend on :8501
	streamlit run ui/app.py

# --- Evaluation ---------------------------------------------------------------
eval:  ## RAGAS evaluation -> reports/ragas_scores.md
	python scripts/run_ragas_eval.py

bench:  ## Baseline vs optimized retrieval A/B -> reports/retrieval_benchmark.md
	python scripts/benchmark_retrieval.py

# --- Containers ---------------------------------------------------------------
docker-build:  ## Build the single-container image (as deployed to HF Spaces)
	docker build -t acme-assistant .

docker-run:  ## Run that image on :7860
	docker run --rm -p 7860:7860 --env-file .env acme-assistant

compose:  ## Run API and UI as separate services (local development)
	docker compose up --build

deploy:  ## Push to a Hugging Face Space: make deploy SPACE=user/space-name
	./deploy/deploy_hf_space.sh "$(SPACE)"

# --- Quality ------------------------------------------------------------------
test:  ## Run the test suite
	pytest

lint:  ## Lint and check formatting
	ruff check .
	ruff format --check .

fmt:  ## Auto-fix lint and format
	ruff check --fix .
	ruff format .

clean:  ## Remove caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache
