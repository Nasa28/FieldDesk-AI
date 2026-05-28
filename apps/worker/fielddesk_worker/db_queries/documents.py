from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb


def get_document_for_update(
    cur, *, document_id: str | UUID, tenant_id: str | UUID
) -> dict[str, Any]:
    cur.execute(
        """
        SELECT id, tenant_id, title, object_key, mime_type, size_bytes, status
        FROM documents
        WHERE id = %s AND tenant_id = %s
        FOR UPDATE
        """,
        (str(document_id), str(tenant_id)),
    )
    row = cur.fetchone()
    if row is None:
        raise ValueError("document not found for tenant")
    return dict(row)


def update_document_status(
    cur,
    *,
    document_id: str | UUID,
    tenant_id: str | UUID,
    status: str,
    parse_error: str | None = None,
) -> None:
    cur.execute(
        """
        UPDATE documents
        SET status = %s,
            parse_error = %s,
            updated_at = now()
        WHERE id = %s AND tenant_id = %s
        """,
        (status, parse_error, str(document_id), str(tenant_id)),
    )


def insert_chunk(
    cur,
    *,
    tenant_id: str | UUID,
    document_id: str | UUID,
    chunk_index: int,
    text: str,
    token_count: int,
    embedding: list[float],
    content_hash: str,
    heading_path: list[str],
    source_page: int | None,
    source_locator: dict[str, Any],
) -> bool:
    """Insert one chunk. Returns True if a new row was written, False if the
    content_hash already existed for this document (idempotent re-ingest)."""
    # halfvec literal: pgvector accepts the standard `[1,2,3]` text form for
    # both vector and halfvec — driver handles the cast through ::halfvec.
    embedding_literal = "[" + ",".join(_format_float(x) for x in embedding) + "]"
    cur.execute(
        """
        INSERT INTO document_chunks
            (tenant_id, document_id, chunk_index, text, token_count,
             embedding, content_hash, heading_path, source_page, source_locator)
        VALUES
            (%s, %s, %s, %s, %s, %s::halfvec, %s, %s, %s, %s)
        ON CONFLICT (document_id, content_hash) WHERE content_hash IS NOT NULL
        DO NOTHING
        """,
        (
            str(tenant_id),
            str(document_id),
            chunk_index,
            text,
            token_count,
            embedding_literal,
            content_hash,
            heading_path,
            source_page,
            Jsonb(source_locator),
        ),
    )
    return cur.rowcount == 1


def delete_existing_chunks(
    cur, *, document_id: str | UUID, tenant_id: str | UUID
) -> int:
    """Clear all chunks for a document before re-ingest. Used when the user
    explicitly re-uploads the same document — UPSERT semantics protect against
    accidental duplication mid-batch but not against drift after a reupload."""
    cur.execute(
        """
        DELETE FROM document_chunks
        WHERE document_id = %s AND tenant_id = %s
        """,
        (str(document_id), str(tenant_id)),
    )
    return cur.rowcount


def _format_float(x: float) -> str:
    # Force a plain decimal representation; Postgres's vector parser doesn't
    # accept Python's default `1e-05` scientific notation.
    return f"{x:.7f}"
