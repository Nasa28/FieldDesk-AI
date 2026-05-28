from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(..., alias="DATABASE_URL")

    s3_endpoint: str | None = Field(default=None, alias="S3_ENDPOINT")
    s3_region: str = Field(default="us-east-1", alias="S3_REGION")
    s3_bucket: str = Field(default="fielddesk", alias="S3_BUCKET")
    s3_access_key_id: str | None = Field(default=None, alias="S3_ACCESS_KEY_ID")
    s3_secret_access_key: str | None = Field(default=None, alias="S3_SECRET_ACCESS_KEY")
    s3_use_ssl: bool = Field(default=False, alias="S3_USE_SSL")

    transcription_provider: str = Field(default="stub", alias="TRANSCRIPTION_PROVIDER")
    transcription_model: str = Field(default="whisper-1", alias="TRANSCRIPTION_MODEL")
    extraction_provider: str = Field(default="stub", alias="EXTRACTION_PROVIDER")
    extraction_model: str = Field(default="gpt-4o-mini", alias="EXTRACTION_MODEL")
    extraction_confidence_threshold: float = Field(
        default=0.7, alias="EXTRACTION_CONFIDENCE_THRESHOLD"
    )
    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")
    embedding_provider: str = Field(default="openai", alias="EMBEDDING_PROVIDER")
    embedding_model: str = Field(default="text-embedding-3-small", alias="EMBEDDING_MODEL")

    # Reranking is opt-in: 'none' (default) skips the rerank pass entirely
    # so the original RRF-fused hybrid_search results pass through unchanged.
    # 'voyage' wires Voyage rerank; 'cohere' wires Cohere Rerank. The worker
    # over-requests
    # `rerank_overrequest` chunks from hybrid_search, then asks the reranker
    # to reorder them down to top_k. Production cost is one rerank call per
    # RAG query; cost lands in ai_model_calls with kind='rerank'.
    rerank_provider: str = Field(default="none", alias="RERANK_PROVIDER")
    rerank_model: str = Field(default="rerank-2.5-lite", alias="RERANK_MODEL")
    rerank_overrequest: int = Field(default=20, alias="RERANK_OVERREQUEST")

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    cohere_api_key: str | None = Field(default=None, alias="COHERE_API_KEY")
    voyage_api_key: str | None = Field(default=None, alias="VOYAGE_API_KEY")

    poll_interval_seconds: float = Field(default=2.0, alias="WORKER_POLL_INTERVAL_SECONDS")
    max_concurrent_jobs: int = Field(default=4, alias="WORKER_MAX_CONCURRENT_JOBS")
    max_retries: int = Field(default=5, alias="WORKER_MAX_RETRIES")
    job_lease_seconds: int = Field(default=900, alias="WORKER_JOB_LEASE_SECONDS")
    job_heartbeat_seconds: int = Field(default=60, alias="WORKER_JOB_HEARTBEAT_SECONDS")


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
