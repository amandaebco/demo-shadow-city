"""Runtime configuration, read from environment variables."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # "rule" = §4.4 mock only; "gemini" = Gemini decides; "gemma" = Gemma first, then Gemini, then rule.
    decider: str
    project_id: str
    firestore_database: str
    gemini_location: str
    gemini_model: str
    gemini_fallback_model: str
    gemini_concurrency: int
    # "" = the model's default thinking; "low" cuts cost ~65% (ml/distillation/README.md).
    gemini_thinking_level: str
    # Layer 2 determinism: replay identical decisions from Firestore decision_cache.
    decision_cache: bool
    # Layer 4 evidence: also write every decision to BigQuery `{dataset}.decisions`. Empty = off.
    bigquery_dataset: str
    # Layer 5: Gemma (Ollama on Cloud Run GPU) for DECIDER=gemma.
    gemma_url: str
    gemma_model: str


def load_settings() -> Settings:
    return Settings(
        decider=os.environ.get("DECIDER", "rule"),
        project_id=os.environ.get("GCP_PROJECT_ID", "ebc-cloud-dev-03"),
        firestore_database=os.environ.get("FIRESTORE_DATABASE", "shadow-city"),
        gemini_location=os.environ.get("GEMINI_LOCATION", "global"),
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"),
        gemini_fallback_model=os.environ.get("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite"),
        gemini_concurrency=int(os.environ.get("GEMINI_CONCURRENCY", "16")),
        gemini_thinking_level=os.environ.get("GEMINI_THINKING_LEVEL", "").lower(),
        decision_cache=os.environ.get("DECISION_CACHE", "on") == "on",
        bigquery_dataset=os.environ.get("BIGQUERY_DATASET", ""),
        gemma_url=os.environ.get("GEMMA_URL", ""),
        gemma_model=os.environ.get("GEMMA_MODEL", "gemma4:e4b"),
    )
