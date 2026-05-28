from enum import StrEnum


class JobType(StrEnum):
    TRANSCRIBE = "transcribe"
    EXTRACT = "extract"
    EMBED = "embed"
    RAG = "rag"
    DRAFT_TICKET = "draft_ticket"


class JobStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRYING = "retrying"
    NEEDS_REVIEW = "needs_review"
