#!/usr/bin/env bash
# Push this project to a Hugging Face Space.
#
# A Space is its own git repository. This script assembles a deployable tree in a temp
# directory and force-pushes it, rather than adding a second remote to your project repo
# — that keeps Space-specific files (the YAML front-matter README) out of the portfolio
# repo a recruiter will actually read.
#
# Prerequisites:
#   1. Create the Space at https://huggingface.co/new-space
#        SDK: Docker    Hardware: CPU basic (free)
#   2. Add secrets under Settings > Variables and secrets:
#        GROQ_API_KEY, PINECONE_API_KEY
#   3. Populate the Pinecone index first — the Space queries an existing index, it does
#      not ingest on boot:
#        python scripts/run_ingestion.py
#   4. Have the HF CLI authenticated:  pip install huggingface_hub && hf auth login
#
# Usage:
#   ./deploy/deploy_hf_space.sh <hf-username>/<space-name>

set -euo pipefail

SPACE="${1:-}"
if [ -z "$SPACE" ]; then
    echo "usage: $0 <hf-username>/<space-name>" >&2
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

echo "Assembling deployment tree for https://huggingface.co/spaces/${SPACE}"

git clone --depth 1 "https://huggingface.co/spaces/${SPACE}" "$STAGING/space" 2>/dev/null || {
    echo "Could not clone the Space. Create it first at https://huggingface.co/new-space" >&2
    exit 1
}

cd "$STAGING/space"

# Clear everything except git metadata, so deleted files do not linger on the Space.
find . -mindepth 1 -maxdepth 1 ! -name '.git' -exec rm -rf {} +

# Only what the Space needs to build and run. Notably absent: tests/, docs/, reports/,
# and the evaluation scripts' outputs — they belong in the portfolio repo, not the demo.
for path in Dockerfile requirements.txt pyproject.toml src api ui scripts data docker; do
    cp -r "${REPO_ROOT}/${path}" .
done

# The Space's README.md must carry the YAML front-matter that configures it.
cp "${REPO_ROOT}/deploy/SPACE_README.md" README.md

# Strip secrets and local artifacts that may exist in the source tree.
rm -f .env
find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
find . -name '*.pyc' -delete 2>/dev/null || true

# Normalise line endings on shell scripts. A CRLF start.sh makes the container's shebang
# request an interpreter whose name ends in a carriage return, and the Space dies with a
# message that says nothing about line endings.
find . -name '*.sh' -exec sed -i 's/\r$//' {} +

if [ -f .env ]; then
    echo "REFUSING TO PUSH: .env is present in the staging tree" >&2
    exit 1
fi

git add -A
if git diff --cached --quiet; then
    echo "No changes to deploy."
    exit 0
fi

git -c user.email="deploy@local" -c user.name="deploy script" \
    commit -q -m "Deploy from $(cd "$REPO_ROOT" && git rev-parse --short HEAD 2>/dev/null || echo 'working tree')"
git push

echo
echo "Deployed. The Space will build for roughly 10-15 minutes (torch and the embedding"
echo "model dominate). Watch the build log at:"
echo "  https://huggingface.co/spaces/${SPACE}?logs=build"
echo
echo "If it starts but the sidebar shows red, check that both secrets are set and that"
echo "the Pinecone index has been populated."
