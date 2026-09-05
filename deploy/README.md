# Deployment

Three ways to run this, in increasing order of permanence.

## 1. Local, two containers (development)

Closest to how this would really be deployed: API and UI as separate services, each
restartable and independently readable in the logs.

```bash
cp .env.example .env      # add GROQ_API_KEY and PINECONE_API_KEY
python scripts/run_ingestion.py --both
docker compose up --build
```

- UI: <http://localhost:8501>
- API docs: <http://localhost:8000/docs>

The UI waits for the API's healthcheck rather than merely for it to start, so the
sidebar is not red on first load.

## 2. Local, single container (what the Space runs)

```bash
docker build -t acme-assistant .
docker run --rm -p 7860:7860 --env-file .env acme-assistant
```

Open <http://localhost:7860>. Verified behaviour:

| | Result |
| --- | --- |
| Image size | 2.9 GB |
| API healthy after | ~34 s (embedding model loads from the baked cache) |
| Container healthy after | ~40 s |
| First `/chat` request | ~3.8 s |
| `docker stop` | 3 s, clean shutdown — SIGTERM is forwarded, not ignored |
| Started with no credentials | Exits immediately naming the missing variables |

## 3. Hugging Face Spaces (the public demo)

Free, no credit card, and gives you a URL to put on a CV.

**Before deploying**, populate Pinecone from your machine. The Space queries an existing
index; it does not ingest on boot.

```bash
python scripts/run_ingestion.py
```

Then:

1. Create the Space at <https://huggingface.co/new-space> — **SDK: Docker**, hardware
   **CPU basic (free)**.
2. Add `GROQ_API_KEY` and `PINECONE_API_KEY` under **Settings → Variables and secrets**.
   Add them as *secrets*, not variables, so they are not printed in build logs.
3. Push:

```bash
./deploy/deploy_hf_space.sh <your-username>/<space-name>
```

The script stages a clean tree in a temp directory and force-pushes it, so Space-specific
files (the YAML front-matter README) never enter the portfolio repo, and `.env` cannot be
pushed by accident.

The first build takes roughly 10–15 minutes; torch and the embedding model dominate.

### Notes specific to Spaces

- **Port 7860.** Spaces expects the app there, which is why Streamlit — not the API — is
  the public service. FastAPI stays on 8000, reachable only inside the container.
- **UID 1000.** Spaces runs containers as that user, so the image creates it and pins the
  HuggingFace caches under its home directory. A cache path outside it fails at runtime
  with a permission error.
- **The model is baked into the image.** Downloading it on first request would make the
  first visitor wait ~25 s and conclude the demo is broken.
- **Free Spaces sleep after ~48 h idle** and cold-start on the next visit. Nothing to be
  done about that on the free tier; it is worth knowing before someone clicks your link
  in an interview.
- **SSE through the Spaces proxy may buffer.** The Streamlit client falls back to the
  non-streaming `/chat` endpoint automatically, so the demo degrades to a slower
  experience rather than a broken one.

## Configuration reference

Every variable is documented in [`.env.example`](../.env.example).

One rule worth repeating: **comments must be on their own lines, never trailing a value.**
`python-dotenv` strips inline `# ...` comments when you run locally, but Docker's
`--env-file` parser does not — it passes the comment through as part of the value, so
`RETRIEVAL_TOP_K=5  # tuned` arrives inside the container as the string `"5  # tuned"`
and fails validation. That failure happens only in the container, which makes it
disproportionately annoying to diagnose.
