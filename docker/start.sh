#!/usr/bin/env bash
# Start FastAPI and Streamlit in one container.
#
# Runs FastAPI in the background and Streamlit in the foreground, so Streamlit is PID 1's
# child and the container's lifetime tracks the user-visible service.
#
# Three things this handles that a naive `uvicorn & streamlit run` does not:
#
#   1. If the API dies, the container exits rather than serving a UI whose every request
#      fails. A dead backend behind a live frontend is the worst of both worlds.
#   2. SIGTERM is forwarded to both processes, so `docker stop` is clean instead of
#      taking the full 10-second kill timeout.
#   3. Streamlit does not start until the API answers /health, so the first visitor never
#      sees "backend not ready" while the embedding model is still loading.

set -euo pipefail

API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8000}"
UI_PORT="${STREAMLIT_SERVER_PORT:-7860}"
API_STARTUP_TIMEOUT="${API_STARTUP_TIMEOUT:-180}"

log() { echo "[start.sh] $*"; }

# --- Configuration sanity ------------------------------------------------------
# Fail loudly and immediately on missing credentials. Without this the container starts
# happily and every question returns an opaque error.
missing=()
[ -z "${GROQ_API_KEY:-}" ] && missing+=("GROQ_API_KEY")
[ -z "${PINECONE_API_KEY:-}" ] && missing+=("PINECONE_API_KEY")

if [ ${#missing[@]} -gt 0 ]; then
    log "FATAL: missing required environment variable(s): ${missing[*]}"
    log "Locally:  docker run --env-file .env ..."
    log "On Hugging Face Spaces: add them under Settings > Variables and secrets."
    exit 1
fi

# --- Shutdown handling ---------------------------------------------------------
api_pid=""
ui_pid=""
watchdog_pid=""

shutdown() {
    log "received shutdown signal, stopping services"
    # Kill the watchdog first, or it observes the API dying during an intentional
    # shutdown and logs a spurious FATAL.
    [ -n "$watchdog_pid" ] && kill -TERM "$watchdog_pid" 2>/dev/null || true
    [ -n "$ui_pid" ] && kill -TERM "$ui_pid" 2>/dev/null || true
    [ -n "$api_pid" ] && kill -TERM "$api_pid" 2>/dev/null || true
    wait 2>/dev/null || true
    exit 0
}
trap shutdown SIGTERM SIGINT

# --- FastAPI -------------------------------------------------------------------
log "starting FastAPI on ${API_HOST}:${API_PORT}"
python -m uvicorn api.main:app --host "$API_HOST" --port "$API_PORT" --workers 1 &
api_pid=$!

# --- Wait for readiness --------------------------------------------------------
# The API's lifespan loads the embedding model, which takes ~10-40s even from the baked
# cache. Polling /health is far more reliable than a fixed sleep.
log "waiting for the API to become healthy (timeout ${API_STARTUP_TIMEOUT}s)"
elapsed=0
until curl -fsS "http://${API_HOST}:${API_PORT}/health" >/dev/null 2>&1; do
    if ! kill -0 "$api_pid" 2>/dev/null; then
        log "FATAL: the API process exited during startup"
        wait "$api_pid" || true
        exit 1
    fi
    if [ "$elapsed" -ge "$API_STARTUP_TIMEOUT" ]; then
        log "FATAL: the API did not become healthy within ${API_STARTUP_TIMEOUT}s"
        kill -TERM "$api_pid" 2>/dev/null || true
        exit 1
    fi
    sleep 2
    elapsed=$((elapsed + 2))
done
log "API healthy after ${elapsed}s"

# Report dependency state once at boot. Non-fatal: a Space with an empty Pinecone index
# should still start and say so on the UI rather than refusing to boot.
if ! curl -fsS "http://${API_HOST}:${API_PORT}/ready" | grep -q '"ready":true'; then
    log "WARNING: /ready reports a dependency problem; the UI sidebar will show which."
fi

# --- Watchdog ------------------------------------------------------------------
# If the API dies later, take the container down so the platform restarts it, rather
# than leaving a UI that fails every request.
#
# Polls with `kill -0` rather than `wait`. In bash, `wait` only works on children of the
# *current* shell -- inside this subshell the API is not a child, so `wait` returns
# immediately and the watchdog would fire the instant it started, killing a perfectly
# healthy container.
watchdog() {
    while kill -0 "$api_pid" 2>/dev/null; do
        sleep 5
    done
    log "FATAL: the API process exited; shutting the container down"
    kill -TERM 1 2>/dev/null || true
}
watchdog &
watchdog_pid=$!

# --- Streamlit -----------------------------------------------------------------
log "starting Streamlit on 0.0.0.0:${UI_PORT}"
streamlit run ui/app.py \
    --server.port "$UI_PORT" \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false &
ui_pid=$!

wait "$ui_pid"
