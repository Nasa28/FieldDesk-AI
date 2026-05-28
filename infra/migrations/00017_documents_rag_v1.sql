-- +goose Up
-- +goose StatementBegin

-- Phase 4 RAG schema refresh. Pre-existing document_chunks table was declared
-- in migration 00007 with vector(1536) + IVFFlat. Mid-2026 production practice
-- (per the research synthesis filed alongside the README): halfvec for ~50%
-- storage reduction with negligible recall loss; HNSW for live-write tables.
-- The table is empty in dev so we can drop + recreate the embedding column
-- rather than ALTER ... TYPE with a cast.

DROP INDEX IF EXISTS document_chunks_embedding_idx;
ALTER TABLE document_chunks DROP COLUMN embedding;
ALTER TABLE document_chunks ADD COLUMN embedding halfvec(1536);

-- Citation metadata: heading_path is the markdown / DOCX section trail
-- (e.g. ['Hydraulic Pumps', 'Troubleshooting']); source_page is the PDF
-- page number; source_locator is the generic JSONB for anything else
-- (line ranges, table cell coordinates, etc.) we may need later.
ALTER TABLE document_chunks ADD COLUMN heading_path   TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE document_chunks ADD COLUMN content_hash   TEXT;
ALTER TABLE document_chunks ADD COLUMN source_page    INTEGER;
ALTER TABLE document_chunks ADD COLUMN source_locator JSONB  NOT NULL DEFAULT '{}'::jsonb;

-- Generated tsvector column for the lexical channel of hybrid retrieval.
-- STORED so the index is cheap to maintain and the column is queryable
-- directly without a CTE in every query.
ALTER TABLE document_chunks
    ADD COLUMN text_search tsvector
    GENERATED ALWAYS AS (to_tsvector('english', text)) STORED;

-- HNSW for dense retrieval. m=16, ef_construction=200 are the 2026 defaults
-- for ~100k-1M chunks per pgvector docs. ef_search is set at query time.
-- (In a populated-production migration we'd use CREATE INDEX CONCURRENTLY
-- outside a transaction; the table is empty in dev so the regular form is
-- fine. Run CONCURRENTLY by hand against a busy prod.)
CREATE INDEX document_chunks_embedding_hnsw_idx
    ON document_chunks USING hnsw (embedding halfvec_cosine_ops)
    WITH (m = 16, ef_construction = 200);

CREATE INDEX document_chunks_text_search_gin_idx
    ON document_chunks USING gin (text_search);

-- Why a partial unique on content_hash: re-ingesting the same document should
-- be idempotent (same chunk -> same hash -> no duplicate row). NULL hash is
-- allowed (legacy rows) so the index excludes them.
CREATE UNIQUE INDEX document_chunks_document_content_hash_unique
    ON document_chunks (document_id, content_hash)
    WHERE content_hash IS NOT NULL;

-- Surface parse errors to operators without losing the document row.
ALTER TABLE documents ADD COLUMN parse_error TEXT;

-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin

ALTER TABLE documents DROP COLUMN IF EXISTS parse_error;

DROP INDEX IF EXISTS document_chunks_document_content_hash_unique;
DROP INDEX IF EXISTS document_chunks_text_search_gin_idx;
DROP INDEX IF EXISTS document_chunks_embedding_hnsw_idx;

ALTER TABLE document_chunks DROP COLUMN IF EXISTS text_search;
ALTER TABLE document_chunks DROP COLUMN IF EXISTS source_locator;
ALTER TABLE document_chunks DROP COLUMN IF EXISTS source_page;
ALTER TABLE document_chunks DROP COLUMN IF EXISTS content_hash;
ALTER TABLE document_chunks DROP COLUMN IF EXISTS heading_path;
ALTER TABLE document_chunks DROP COLUMN IF EXISTS embedding;
ALTER TABLE document_chunks ADD COLUMN embedding vector(1536);
CREATE INDEX document_chunks_embedding_idx
    ON document_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
-- +goose StatementEnd
