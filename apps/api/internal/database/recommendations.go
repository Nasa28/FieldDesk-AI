package database

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
)

// EnrichedCitation is one citation surfaced to API clients. The synthesis LLM
// only emits chunk_id (and optionally a free-text note) because we explicitly
// don't trust the model to echo document titles — that would be a vector for
// a hostile chunk to mis-attribute a real safety procedure. Document metadata
// is looked up server-side from the rag_queries.results that drove the
// synthesis, which is the authoritative source. Hallucinated chunk_ids (ones
// the model emitted that weren't in the retrieval set) are dropped during
// enrichment rather than rendered with "(unknown source)" — the UI shouldn't
// give equal billing to a citation we can't trace.
type EnrichedCitation struct {
	ChunkID       string     `json:"chunk_id"`
	Note          *string    `json:"note,omitempty"`
	DocumentID    *uuid.UUID `json:"document_id,omitempty"`
	DocumentTitle *string    `json:"document_title,omitempty"`
	HeadingPath   []string   `json:"heading_path,omitempty"`
	SourcePage    *int       `json:"source_page,omitempty"`
}

// TicketRecommendation is the API-facing, denormalized view of the latest
// ticket_recommendations row. Fields that live inside the synthesis output
// JSONB on the worker side (suggested_parts, safety_checklist, citations,
// etc.) are flattened to the top level so API consumers don't have to know
// the storage detail "the recs are inside an output envelope." This is the
// shape /v1/tickets/{id}/recommendations returns.
//
// Why a separate view type instead of mutating the row in-place: keeps the
// DB-storage concept (a row with a JSONB column) decoupled from the wire
// concept (a flat object with enriched citations). Future shape changes
// don't force downstream consumers to re-derive nested paths.
type TicketRecommendation struct {
	ID          uuid.UUID  `json:"id"`
	TenantID    uuid.UUID  `json:"tenant_id"`
	JobTicketID uuid.UUID  `json:"job_ticket_id"`
	RAGQueryID  *uuid.UUID `json:"rag_query_id,omitempty"`

	// Synthesis output (flattened from the storage row's `output` JSONB).
	PossibleDiagnosis   *string            `json:"possible_diagnosis,omitempty"`
	SuggestedParts      []string           `json:"suggested_parts"`
	SafetyChecklist     []string           `json:"safety_checklist"`
	FollowUpQuestions   []string           `json:"follow_up_questions"`
	Citations           []EnrichedCitation `json:"citations"`
	InsufficientContext bool               `json:"insufficient_context"`
	Notes               *string            `json:"notes,omitempty"`

	// Operator-relevant signals. confidence is sourced from the JSONB
	// output (validated by the worker's pydantic schema) rather than the
	// row's nullable confidence column — the worker writes them in sync
	// but the JSONB value is the canonical post-validation number.
	Confidence float64 `json:"confidence"`
	JSONValid  bool    `json:"json_valid"`

	// Provenance.
	Provider      string  `json:"provider"`
	Model         string  `json:"model"`
	PromptVersion string  `json:"prompt_version"`
	SchemaVersion string  `json:"schema_version"`
	InputTokens   int     `json:"input_tokens"`
	OutputTokens  int     `json:"output_tokens"`
	CostUSD       float64 `json:"cost_usd"`
	DurationMS    int     `json:"duration_ms"`
	ErrorMessage  *string `json:"error_message,omitempty"`

	CreatedAt time.Time `json:"created_at"`
}

// rawCitation mirrors the citation shape the worker writes inside
// ticket_recommendations.output (see recommendations/schema.py Citation).
// Used only as the unmarshal target — callers see EnrichedCitation.
type rawCitation struct {
	ChunkID string  `json:"chunk_id"`
	Note    *string `json:"note,omitempty"`
}

// rawSynthesisOutput mirrors RecommendationsOutput from the worker. Lives in
// this file because it's the inverse of what the worker writes; if the
// worker schema changes, both sides change together.
type rawSynthesisOutput struct {
	PossibleDiagnosis   *string       `json:"possible_diagnosis"`
	SuggestedParts      []string      `json:"suggested_parts"`
	SafetyChecklist     []string      `json:"safety_checklist"`
	FollowUpQuestions   []string      `json:"follow_up_questions"`
	Citations           []rawCitation `json:"citations"`
	Confidence          float64       `json:"confidence"`
	InsufficientContext bool          `json:"insufficient_context"`
	Notes               *string       `json:"notes"`
}

const latestRecommendationForTicketSQL = `
	SELECT r.id, r.tenant_id, r.job_ticket_id, r.rag_query_id,
	       r.output, r.confidence,
	       r.provider, r.model, r.prompt_version, r.schema_version,
	       r.input_tokens, r.output_tokens, r.cost_usd, r.duration_ms,
	       r.json_valid, r.error_message, r.created_at,
	       rq.results AS rag_results
	FROM ticket_recommendations r
	LEFT JOIN rag_queries rq
	       ON rq.id = r.rag_query_id
	      AND rq.tenant_id = r.tenant_id
	      AND rq.job_ticket_id = r.job_ticket_id
	WHERE r.tenant_id = $1 AND r.job_ticket_id = $2
	ORDER BY r.created_at DESC
	LIMIT 1
`

// GetLatestRecommendationForTicket returns the most recent
// ticket_recommendations row for a ticket, flattened to the wire shape and
// with citations enriched against the rag_queries.results that drove the
// synthesis. Returns ErrNotFound when no row exists yet (synthesis job
// still pending — the API surfaces this as 404, the UI renders "pending").
//
// One round-trip: the JOIN pulls the rag_queries.results blob alongside the
// recs row so the citation lookup happens in Go without a second query. The
// LEFT JOIN handles the zero-chunk short-circuit case (rag_query_id NULL or
// the rag_queries row was deleted) without nullifying the recs row itself.
func GetLatestRecommendationForTicket(
	ctx context.Context, db *DB, ticketID, tenantID uuid.UUID,
) (TicketRecommendation, error) {
	var (
		id            uuid.UUID
		tID           uuid.UUID
		jobTicketID   uuid.UUID
		ragQueryID    *uuid.UUID
		outputRaw     []byte
		rowConfidence *float64
		provider      string
		model         string
		promptVersion string
		schemaVersion string
		inputTokens   int
		outputTokens  int
		cost          pgtype.Numeric
		durationMS    int
		jsonValid     bool
		errorMessage  *string
		createdAt     time.Time
		ragResultsRaw []byte
	)
	err := db.QueryRow(ctx, latestRecommendationForTicketSQL, tenantID, ticketID).Scan(
		&id, &tID, &jobTicketID, &ragQueryID,
		&outputRaw, &rowConfidence,
		&provider, &model, &promptVersion, &schemaVersion,
		&inputTokens, &outputTokens, &cost, &durationMS,
		&jsonValid, &errorMessage, &createdAt,
		&ragResultsRaw,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return TicketRecommendation{}, ErrNotFound
	}
	if err != nil {
		return TicketRecommendation{}, err
	}

	view := TicketRecommendation{
		ID:            id,
		TenantID:      tID,
		JobTicketID:   jobTicketID,
		RAGQueryID:    ragQueryID,
		Provider:      provider,
		Model:         model,
		PromptVersion: promptVersion,
		SchemaVersion: schemaVersion,
		InputTokens:   inputTokens,
		OutputTokens:  outputTokens,
		CostUSD:       numericToFloat(cost),
		DurationMS:    durationMS,
		JSONValid:     jsonValid,
		ErrorMessage:  errorMessage,
		CreatedAt:     createdAt,
		// Default to empty slices, not nil, so the wire shape is stable —
		// clients don't have to special-case "missing" vs "empty list."
		SuggestedParts:    []string{},
		SafetyChecklist:   []string{},
		FollowUpQuestions: []string{},
		Citations:         []EnrichedCitation{},
	}

	if err := applySynthesisOutput(&view, outputRaw, rowConfidence); err != nil {
		// Don't fail the request on a malformed output blob — the row's
		// json_valid + error_message already signal this case to the
		// operator. Surface what we can; the worker already chose what to
		// persist when the model emitted bad JSON.
		view.InsufficientContext = true
		if view.Notes == nil {
			note := "Stored output failed to unmarshal: " + err.Error()
			view.Notes = &note
		}
	}

	view.Citations = enrichCitations(view.Citations, ragResultsRaw)
	return view, nil
}

// applySynthesisOutput unmarshals the ticket_recommendations.output JSONB
// into the flat view. confidence is sourced from the unmarshaled blob (the
// post-validation value) and only falls back to the row's nullable column
// if the blob doesn't carry one — which would itself be a sign of a
// degraded persistence path.
func applySynthesisOutput(
	view *TicketRecommendation, outputRaw []byte, rowConfidence *float64,
) error {
	if len(outputRaw) == 0 {
		if rowConfidence != nil {
			view.Confidence = *rowConfidence
		}
		return nil
	}
	var out rawSynthesisOutput
	if err := json.Unmarshal(outputRaw, &out); err != nil {
		if rowConfidence != nil {
			view.Confidence = *rowConfidence
		}
		return err
	}
	view.PossibleDiagnosis = out.PossibleDiagnosis
	if out.SuggestedParts != nil {
		view.SuggestedParts = out.SuggestedParts
	}
	if out.SafetyChecklist != nil {
		view.SafetyChecklist = out.SafetyChecklist
	}
	if out.FollowUpQuestions != nil {
		view.FollowUpQuestions = out.FollowUpQuestions
	}
	view.InsufficientContext = out.InsufficientContext
	view.Notes = out.Notes
	view.Confidence = out.Confidence
	if out.Confidence == 0 && rowConfidence != nil {
		// Treat exact-zero in the blob as "not set" only when the row
		// column has a value — otherwise zero is a legitimate confidence
		// (the worker writes 0.0 explicitly for degraded outputs).
		view.Confidence = *rowConfidence
	}
	// Translate raw citations to the unenriched EnrichedCitation form so
	// enrichCitations has a uniform input shape.
	view.Citations = make([]EnrichedCitation, 0, len(out.Citations))
	for _, c := range out.Citations {
		if c.ChunkID == "" {
			continue
		}
		view.Citations = append(view.Citations, EnrichedCitation{
			ChunkID: c.ChunkID,
			Note:    c.Note,
		})
	}
	return nil
}

// enrichCitations joins each citation's chunk_id against the rag_queries
// retrieval set that produced the synthesis. Hallucinated chunk_ids (ones
// the model emitted that weren't in the retrieval set) are dropped — the
// operator should see only citations we can trace back to a real chunk.
//
// When ragResultsRaw is empty (insufficient_context short-circuit, or the
// rag_queries row was removed) every citation is treated as hallucinated.
// That matches the worker's contract: a real synthesis cites real chunks
// from the rag_query that drove it.
func enrichCitations(
	citations []EnrichedCitation, ragResultsRaw []byte,
) []EnrichedCitation {
	if len(citations) == 0 {
		return citations
	}
	lookup := buildChunkLookup(ragResultsRaw)
	if len(lookup) == 0 {
		return []EnrichedCitation{}
	}
	out := make([]EnrichedCitation, 0, len(citations))
	for _, c := range citations {
		ref, ok := lookup[c.ChunkID]
		if !ok {
			continue
		}
		enriched := c
		enriched.DocumentID = &ref.DocumentID
		enriched.DocumentTitle = &ref.DocumentTitle
		// HeadingPath defaults to an empty slice in the rag layer; pass
		// it through unconditionally so clients always render the same
		// shape (an empty array, not a missing key).
		enriched.HeadingPath = ref.HeadingPath
		if ref.SourcePage != nil {
			enriched.SourcePage = ref.SourcePage
		}
		out = append(out, enriched)
	}
	return out
}

// chunkRef is the subset of rag_queries.results we need to enrich a
// citation. We deliberately don't pull text — the synthesis card shows the
// citation header only; the chunk text lives in the RelatedDocuments card
// directly above.
type chunkRef struct {
	ChunkID       string    `json:"chunk_id"`
	DocumentID    uuid.UUID `json:"document_id"`
	DocumentTitle string    `json:"document_title"`
	HeadingPath   []string  `json:"heading_path"`
	SourcePage    *int      `json:"source_page,omitempty"`
}

func buildChunkLookup(ragResultsRaw []byte) map[string]chunkRef {
	if len(ragResultsRaw) == 0 {
		return nil
	}
	var refs []chunkRef
	if err := json.Unmarshal(ragResultsRaw, &refs); err != nil {
		return nil
	}
	lookup := make(map[string]chunkRef, len(refs))
	for _, r := range refs {
		if r.ChunkID == "" {
			continue
		}
		lookup[r.ChunkID] = r
	}
	return lookup
}
