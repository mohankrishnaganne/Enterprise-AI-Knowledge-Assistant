"""Central configuration.

Every tunable in this project is declared here and nowhere else. Modules import the
`settings` singleton rather than reading ``os.environ`` directly, which keeps the
ingestion pipeline, the agent, the API and the evaluation scripts provably in sync --
important because the retrieval benchmark is only meaningful if the "optimized" arm uses
exactly the same parameters the live app uses.

Values are read from a ``.env`` file (see ``.env.example``) with environment variables
taking precedence.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root: this file is src/config.py, so two parents up.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
EVAL_DATA_DIR = DATA_DIR / "eval"
GOLDEN_DATASET_PATH = EVAL_DATA_DIR / "golden_dataset.json"
REPORTS_DIR = PROJECT_ROOT / "reports"

# The corpus taxonomy. These are also the directory names under data/raw/ and the
# allowed values of the `category` metadata field used for Pinecone filtering.
Category = Literal["technical", "operational", "business"]
CATEGORIES: tuple[str, ...] = ("technical", "operational", "business")


class Settings(BaseSettings):
    """Typed application settings loaded from the environment."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- LLM (Groq) -----------------------------------------------------------
    groq_api_key: str = Field(default="", description="Groq API key; required at query time.")
    # Groq retires models periodically. `src.agent.llm.check_models_available()`
    # validates these ids against the live API rather than failing later as a 404.
    groq_model_strong: str = "openai/gpt-oss-120b"
    groq_model_fast: str = "openai/gpt-oss-20b"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 1024

    # --- Vector database (Pinecone) -------------------------------------------
    pinecone_api_key: str = Field(default="", description="Pinecone API key; required to ingest.")
    pinecone_index_name: str = "enterprise-knowledge"
    pinecone_cloud: str = "aws"
    pinecone_region: str = "us-east-1"
    pinecone_namespace: str = "v1"
    # Naive chunks live in their own namespace so the A/B benchmark needs only the
    # single index the Pinecone free tier allows.
    pinecone_baseline_namespace: str = "baseline"

    # --- Embeddings -----------------------------------------------------------
    # Two backends produce *identical* vectors for the same model, verified at
    # cosine 1.000000, so the same Pinecone index serves both and the retrieval
    # benchmark stays valid whichever is in use:
    #   "local"  - sentence-transformers on CPU. No network, no rate limit, but
    #              needs torch (~2GB installed) and a 130MB model download.
    #   "hf_api" - HuggingFace Inference API. Nothing to install beyond
    #              huggingface_hub, which is what makes the app deployable on a
    #              free tier that cannot hold torch.
    embedding_backend: Literal["local", "hf_api"] = "local"
    hf_token: str = Field(default="", description="HuggingFace token; required by hf_api.")
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    embedding_device: str = "cpu"
    embedding_batch_size: int = 32

    # --- Chunking (the optimized arm; the baseline arm is defined in chunker.py) --
    chunk_size: int = 800
    chunk_overlap: int = 120

    # --- Retrieval ------------------------------------------------------------
    retrieval_top_k: int = 6
    retrieval_fetch_k: int = 20
    retrieval_mmr_lambda: float = 0.5
    retrieval_score_threshold: float = 0.35

    # --- Agent behaviour ------------------------------------------------------
    max_query_rewrites: int = 2
    max_subqueries: int = 3

    # --- Serving --------------------------------------------------------------
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_base_url: str = "http://localhost:8000"
    log_level: str = "INFO"

    @field_validator("chunk_overlap")
    @classmethod
    def _overlap_must_be_smaller_than_chunk(cls, value: int, info) -> int:
        """Guard against a config that would make the splitter loop or error out."""
        chunk_size = info.data.get("chunk_size", 800)
        if value >= chunk_size:
            raise ValueError(f"CHUNK_OVERLAP ({value}) must be < CHUNK_SIZE ({chunk_size})")
        return value

    @field_validator("retrieval_mmr_lambda")
    @classmethod
    def _lambda_in_unit_interval(cls, value: float) -> float:
        """MMR lambda trades relevance (1.0) against diversity (0.0)."""
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"RETRIEVAL_MMR_LAMBDA must be in [0, 1], got {value}")
        return value

    def require_groq(self) -> str:
        """Return the Groq key, raising a clear error if it is missing.

        Called lazily by the LLM factory so that importing the package (and running
        unit tests) never requires credentials.
        """
        if not self.groq_api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Copy .env.example to .env and add a key from "
                "https://console.groq.com/keys"
            )
        return self.groq_api_key

    def require_hf_token(self) -> str:
        """Return the HuggingFace token, raising a clear error if it is missing."""
        if not self.hf_token:
            raise RuntimeError(
                "EMBEDDING_BACKEND is 'hf_api' but HF_TOKEN is not set. Create a token at "
                "https://huggingface.co/settings/tokens (read scope is enough), or set "
                "EMBEDDING_BACKEND=local to embed on this machine instead."
            )
        return self.hf_token

    def require_pinecone(self) -> str:
        """Return the Pinecone key, raising a clear error if it is missing."""
        if not self.pinecone_api_key:
            raise RuntimeError(
                "PINECONE_API_KEY is not set. Copy .env.example to .env and add a key from "
                "https://app.pinecone.io"
            )
        return self.pinecone_api_key


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()


# Convenience alias so callers can simply `from src.config import settings`.
settings = get_settings()
