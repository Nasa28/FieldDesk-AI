-- +goose Up
-- +goose StatementBegin

-- Store a retrieval-only version of the chunk text. Raw `text` remains the
-- citation/UI surface; `retrieval_text` carries document/section/page context
-- for embeddings and the lexical channel.
ALTER TABLE document_chunks ADD COLUMN retrieval_text TEXT;
UPDATE document_chunks SET retrieval_text = text WHERE retrieval_text IS NULL;
ALTER TABLE document_chunks ALTER COLUMN retrieval_text SET NOT NULL;

DROP INDEX IF EXISTS document_chunks_text_search_gin_idx;
ALTER TABLE document_chunks DROP COLUMN IF EXISTS text_search;
ALTER TABLE document_chunks
    ADD COLUMN text_search tsvector
    GENERATED ALWAYS AS (to_tsvector('english', retrieval_text)) STORED;
CREATE INDEX document_chunks_text_search_gin_idx
    ON document_chunks USING gin (text_search);

-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin

DROP INDEX IF EXISTS document_chunks_text_search_gin_idx;
ALTER TABLE document_chunks DROP COLUMN IF EXISTS text_search;
ALTER TABLE document_chunks
    ADD COLUMN text_search tsvector
    GENERATED ALWAYS AS (to_tsvector('english', text)) STORED;
CREATE INDEX document_chunks_text_search_gin_idx
    ON document_chunks USING gin (text_search);
ALTER TABLE document_chunks DROP COLUMN IF EXISTS retrieval_text;

-- +goose StatementEnd
