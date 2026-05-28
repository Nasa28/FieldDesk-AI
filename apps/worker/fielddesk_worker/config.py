"""Worker configuration loaded from environment variables."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(..., alias="DATABASE_URL")

    s3_endpoint: str | None = Field(default=None, alias="S3_ENDPOINT")
    s3_region: str = Field(default="us-east-1", alias="S3_REGION")
    s3_bucket: str = Field(default="fielddesk", alias="S3_BUCKET")
    s3_access_key: str | None = Field(default=None, alias="S3_ACCESS_KEY")
    s3_secret_key: str | None = Field(default=None, alias="S3_SECRET_KEY")

    transcription_provider: str = Field(default="openai", alias="TRANSCRIPTION_PROVIDER")
    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")
    embedding_provider: str = Field(default="openai", alias="EMBEDDING_PROVIDER")

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")

    poll_interval_seconds: float = Field(default=2.0, alias="WORKER_POLL_INTERVAL_SECONDS")
    max_concurrent_jobs: int = Field(default=4, alias="WORKER_MAX_CONCURRENT_JOBS")
    max_retries: int = Field(default=5, alias="WORKER_MAX_RETRIES")


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
