package database

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
)

// RetrievedChunk is one row from a hybrid retrieval call. fused_score is the
// reciprocal-rank-fusion (RRF) score used to order the result; the individual
// ranks are exposed so the UI can show "ranked #2 by vector, #5 by lexical"
// for transparency when an operator wonders why a chunk is at the top.
type RetrievedChunk struct {
	ChunkID       uuid.UUID       `json:"chunk_id"`
	DocumentID    uuid.UUID       `json:"document_id"`
	DocumentTitle string          `json:"document_title"`
	Text          string          `json:"text"`
	HeadingPath   []string        `json:"heading_path"`
	SourcePage    *int            `json:"source_page,omitempty"`
	SourceLocator json.RawMessage `json:"source_locator,omitempty"`
	DenseRank     *int            `json:"dense_rank,omitempty"`
	LexicalRank   *int            `json:"lexical_rank,omitempty"`
	FusedScore    float64         `json:"fused_score"`
}

// HybridSearchParams is everything you need to retrieve.
// QueryEmbedding must already be computed; this layer does no embedding —
// it's a pure DB query so the embedding provider stays in one place (worker).
type HybridSearchParams struct {
	TenantID       uuid.UUID
	QueryEmbedding []float32 // 1536-dim halfvec literal will be built from this
	QueryText      string    // used for the lexical (tsvector) channel
	TopK           int       // typical 5; capped at 50 to keep RRF math sane
	Candidates     int       // how many candidates per channel before fusion (default 50)
	RRFK           int       // RRF smoothing constant; default 60 per Cormack et al.
}

// HybridSearch runs dense + lexical retrieval and fuses with RRF in a single
// SQL statement, scoped to the tenant. The single-query design (CTEs + LEFT
// JOIN) avoids two roundtrips and lets Postgres plan the join across the two
// channels. RRF is the consensus 2026 fusion method per the research notes
// alongside this code; tunable via RRFK if a tenant's eval shows another
// value works better.
func HybridSearch(ctx context.Context, db *DB, p HybridSearchParams) ([]RetrievedChunk, error) {
	topK := p.TopK
	if topK <= 0 || topK > 50 {
		topK = 5
	}
	candidates := p.Candidates
	if candidates <= 0 {
		candidates = 50
	}
	rrfK := p.RRFK
	if rrfK <= 0 {
		rrfK = 60
	}
	if len(p.QueryEmbedding) == 0 {
		return nil, errors.New("hybrid search requires a query embedding")
	}
	queryText := strings.TrimSpace(p.QueryText)
	// websearch_to_tsquery accepts an empty input cleanly (matches nothing),
	// so the dense channel still works on its own when the query text is
	// blank — e.g. when retrieving by an extracted-ticket vector with no
	// natural-language form to send to the lexical side.
	tsQuery := queryText

	// Build the halfvec literal in Go; the driver does not have a native
	// halfvec encoder yet. The cast to ::halfvec(1536) keeps the planner
	// happy when the column uses halfvec_cosine_ops.
	embeddingLit := formatHalfvecLiteral(p.QueryEmbedding)

	const q = `
WITH dense AS (
    SELECT
        c.id,
        c.document_id,
        c.text,
        c.heading_path,
        c.source_page,
        c.source_locator,
        ROW_NUMBER() OVER (ORDER BY c.embedding <=> $1::halfvec) AS rank_dense
    FROM document_chunks c
    WHERE c.tenant_id = $4
    ORDER BY c.embedding <=> $1::halfvec
    LIMIT $2
),
lexical AS (
    SELECT
        c.id,
        c.document_id,
        c.text,
        c.heading_path,
        c.source_page,
        c.source_locator,
        ROW_NUMBER() OVER (
            ORDER BY ts_rank_cd(c.text_search, websearch_to_tsquery('english', $5)) DESC
        ) AS rank_lexical
    FROM document_chunks c
    WHERE c.tenant_id = $4
      AND ($5 = '' OR c.text_search @@ websearch_to_tsquery('english', $5))
    ORDER BY ts_rank_cd(c.text_search, websearch_to_tsquery('english', $5)) DESC
    LIMIT $2
),
fused AS (
    SELECT
        COALESCE(d.id, l.id)              AS chunk_id,
        COALESCE(d.document_id, l.document_id) AS document_id,
        COALESCE(d.text, l.text)          AS text,
        COALESCE(d.heading_path, l.heading_path) AS heading_path,
        COALESCE(d.source_page, l.source_page)   AS source_page,
        COALESCE(d.source_locator, l.source_locator) AS source_locator,
        d.rank_dense,
        l.rank_lexical,
        (CASE WHEN d.rank_dense   IS NULL THEN 0.0 ELSE 1.0 / ($3 + d.rank_dense)   END
       + CASE WHEN l.rank_lexical IS NULL THEN 0.0 ELSE 1.0 / ($3 + l.rank_lexical) END) AS fused_score
    FROM dense d
    FULL OUTER JOIN lexical l ON l.id = d.id
)
SELECT
    f.chunk_id,
    f.document_id,
    docs.title       AS document_title,
    f.text,
    f.heading_path,
    f.source_page,
    f.source_locator,
    f.rank_dense,
    f.rank_lexical,
    f.fused_score
FROM fused f
JOIN documents docs ON docs.id = f.document_id AND docs.tenant_id = $4
WHERE f.fused_score > 0
ORDER BY f.fused_score DESC
LIMIT $6
`

	rows, err := db.Query(ctx, q,
		embeddingLit, // $1 query embedding
		candidates,   // $2 per-channel candidate cap
		rrfK,         // $3 RRF smoothing constant
		p.TenantID,   // $4 tenant scope
		tsQuery,      // $5 lexical query string
		topK,         // $6 final cap
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := make([]RetrievedChunk, 0, topK)
	for rows.Next() {
		var (
			r       RetrievedChunk
			locator []byte
		)
		if err := rows.Scan(
			&r.ChunkID, &r.DocumentID, &r.DocumentTitle, &r.Text, &r.HeadingPath,
			&r.SourcePage, &locator, &r.DenseRank, &r.LexicalRank, &r.FusedScore,
		); err != nil {
			return nil, err
		}
		r.SourceLocator = json.RawMessage(locator)
		out = append(out, r)
	}
	return out, rows.Err()
}

// InsertRAGQuery logs the query + results into rag_queries for later
// dashboards / replay / cost attribution. The hybrid SQL doesn't write this
// row itself because the worker also needs to attribute the embedding cost
// (a separate ai_model_calls row) before persisting the audit trail.
type InsertRAGQueryParams struct {
	TenantID       uuid.UUID
	JobTicketID    *uuid.UUID
	QueryText      string
	TopK           int
	Results        []RetrievedChunk
	EmbeddingModel string
	CostUSD        float64
	DurationMS     int
}

func InsertRAGQuery(ctx context.Context, db *DB, p InsertRAGQueryParams) (uuid.UUID, error) {
	results, err := json.Marshal(p.Results)
	if err != nil {
		return uuid.UUID{}, err
	}
	const q = `
		INSERT INTO rag_queries
			(tenant_id, job_ticket_id, query_text, top_k, results,
			 embedding_model, cost_usd, duration_ms)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
		RETURNING id
	`
	var id uuid.UUID
	err = db.QueryRow(ctx, q,
		p.TenantID, p.JobTicketID, p.QueryText, p.TopK, results,
		p.EmbeddingModel, p.CostUSD, p.DurationMS,
	).Scan(&id)
	return id, err
}

type RAGQuery struct {
	ID             uuid.UUID       `json:"id"`
	TenantID       uuid.UUID       `json:"tenant_id"`
	JobTicketID    *uuid.UUID      `json:"job_ticket_id,omitempty"`
	QueryText      string          `json:"query_text"`
	TopK           int             `json:"top_k"`
	Results        json.RawMessage `json:"results"`
	EmbeddingModel *string         `json:"embedding_model,omitempty"`
	CostUSD        float64         `json:"cost_usd"`
	DurationMS     int             `json:"duration_ms"`
	CreatedAt      time.Time       `json:"created_at"`
}

// GetLatestRAGQueryForTicket returns the most recent rag_queries row for a
// ticket, or ErrNotFound if none exist. Used by the ticket detail view so
// "Related documents" shows the freshest retrieval.
func GetLatestRAGQueryForTicket(
	ctx context.Context, db *DB, ticketID, tenantID uuid.UUID,
) (RAGQuery, error) {
	const q = `
		SELECT id, tenant_id, job_ticket_id, query_text, top_k, results,
		       embedding_model, cost_usd, duration_ms, created_at
		FROM rag_queries
		WHERE tenant_id = $1 AND job_ticket_id = $2
		ORDER BY created_at DESC
		LIMIT 1
	`
	var r RAGQuery
	var cost pgtype.Numeric
	var results []byte
	err := db.QueryRow(ctx, q, tenantID, ticketID).Scan(
		&r.ID, &r.TenantID, &r.JobTicketID, &r.QueryText, &r.TopK, &results,
		&r.EmbeddingModel, &cost, &r.DurationMS, &r.CreatedAt,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return RAGQuery{}, ErrNotFound
	}
	if err != nil {
		return RAGQuery{}, err
	}
	r.Results = json.RawMessage(results)
	r.CostUSD = numericToFloat(cost)
	return r, nil
}

// formatHalfvecLiteral emits "[1.234,5.678,...]" — the textual form pgvector
// accepts for vector / halfvec inputs. Using plain %g avoids scientific
// notation that the pgvector parser refuses.
func formatHalfvecLiteral(v []float32) string {
	var b strings.Builder
	b.Grow(len(v) * 12)
	b.WriteByte('[')
	for i, x := range v {
		if i > 0 {
			b.WriteByte(',')
		}
		fmt.Fprintf(&b, "%.7f", x)
	}
	b.WriteByte(']')
	return b.String()
}
