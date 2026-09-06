# Enterprise AI Knowledge Assistant — single image running both services.
#
# Deliberately one container rather than two, because the free Hugging Face Spaces tier
# runs exactly one. Streamlit is the public face on 7860 (the port Spaces expects) and
# FastAPI listens on 8000, reachable only from inside the container. docker-compose.yml
# splits them into two services for local development.
#
# Two build-time decisions worth stating:
#
#   1. requirements.txt pins the CPU torch build via an extra index. The default PyPI
#      wheel bundles CUDA and pulls ~2.5GB of nvidia packages, useless on a CPU host.
#   2. The embedding model is downloaded at BUILD time, not on first request. It is
#      ~130MB; fetching it lazily makes the first user question take ~25s and look
#      broken, while later ones take 4s. This was measured, not assumed.
#
# Local use:
#   docker build -t acme-assistant .
#   docker run --rm -p 7860:7860 --env-file .env acme-assistant

FROM python:3.12-slim

# HF Spaces runs containers as UID 1000. Creating that user here means the same image
# works locally and on Spaces without permission surprises in the caches.
RUN useradd -m -u 1000 app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/home/app/.cache/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/home/app/.cache/huggingface \
    HF_HUB_DISABLE_SYMLINKS_WARNING=1 \
    STREAMLIT_SERVER_PORT=7860 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    API_HOST=127.0.0.1 \
    API_PORT=8000 \
    API_BASE_URL=http://127.0.0.1:8000

# curl is used by the healthcheck and by the startup script's readiness wait.
# dos2unix guards against a CRLF checkout of the startup script (see below).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl dos2unix \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Dependencies -------------------------------------------------------------
# Installed before application code is copied, so editing source does not invalidate
# the (very expensive) dependency layer.
COPY requirements.txt ./

# requirements.txt carries the CPU-torch extra index and pins torch==2.5.1+cpu on
# Linux, so no separate torch step is needed. reportlab is added on its own because
# the corpus-generation step below needs it; the rest of requirements-dev.txt
# (RAGAS, pytest, ruff) is never used at runtime and would only add weight.
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir reportlab==5.0.1

# --- Application --------------------------------------------------------------
COPY --chown=app:app src/ ./src/
COPY --chown=app:app api/ ./api/
COPY --chown=app:app ui/ ./ui/
COPY --chown=app:app scripts/ ./scripts/
COPY --chown=app:app data/ ./data/
COPY --chown=app:app docker/start.sh ./docker/start.sh
COPY --chown=app:app pyproject.toml ./

# Normalise line endings before making the script executable. This repo is developed on
# Windows, and a CRLF start.sh turns the shebang into a request for an interpreter whose
# name ends in a carriage return. The container then dies with
# "env: 'bash\r': No such file or directory" -- an error that gives no hint that line
# endings are the cause. .gitattributes prevents this at checkout; this is the
# belt-and-braces for any build context that still carries CRLF.
RUN dos2unix -q ./docker/start.sh \
    && chmod +x ./docker/start.sh \
    && mkdir -p /home/app/.cache \
    && chown -R app:app /home/app /app

USER app

# --- Bake the embedding model into the image ----------------------------------
# Runs as `app` so the cache lands where the runtime user can read it.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5'); print('embedding model cached into image')"

# --- Regenerate the corpus PDFs -----------------------------------------------
# The generated PDFs are gitignored (they are build artifacts), so they are rebuilt here
# or the two PDF-sourced documents would be missing from the index.
RUN python scripts/generate_corpus.py

EXPOSE 7860

# Probe Streamlit rather than the API: it is the user-visible service, and it only starts
# after the API is already healthy. The long start period covers model load.
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -fsS http://127.0.0.1:7860/_stcore/health || exit 1

CMD ["./docker/start.sh"]
