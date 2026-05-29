package realtime

import (
	"context"
	"encoding/json"
	"fmt"
	"hash/fnv"
	"strings"
	"time"

	"github.com/fielddesk-ai/api/internal/database"
	"github.com/google/uuid"
)

const (
	voiceTopK         = 6
	maxToolChunks     = 8
	maxToolChunkChars = 1200
	retrievalTimeout  = 8 * time.Second
	retrievalPoll     = 400 * time.Millisecond
)

// runKnowledgeSearch fulfils a search_knowledge_base tool call by reusing the
// existing async `rag` ai-job pipeline: enqueue a retrieval-only job, poll for
// its result, and shape the chunks into the tool response the model receives.
// Reusing the rag job means retrieval, tenant isolation, budget gating, and
// cost logging are all inherited — no new retrieval code in Go.
func (h *Handler) runKnowledgeSearch(ctx context.Context, tenantID uuid.UUID, args map[string]any) map[string]any {
	query, _ := args["query"].(string)
	query = strings.TrimSpace(query)
	if query == "" {
		return emptyToolResponse("No search query was provided.")
	}
	if len(query) > 4000 {
		query = query[:4000]
	}

	payload, err := json.Marshal(map[string]any{
		"tenant_id":  tenantID.String(),
		"query_text": query,
		"top_k":      voiceTopK,
		"source":     "voice",
		"answer":     false,
	})
	if err != nil {
		return emptyToolResponse("Could not start a knowledge-base search.")
	}

	job, err := database.EnqueueAIJob(ctx, h.db, database.EnqueueAIJobParams{
		TenantID:       tenantID,
		Type:           "rag",
		Payload:        payload,
		IdempotencyKey: fmt.Sprintf("rag:voice:%s:%d:%x", tenantID, voiceTopK, hashQuery(query)),
		MaxAttempts:    h.maxJobs,
	})
	if err != nil {
		h.log.Warn("realtime: enqueue rag job", "error", err)
		return emptyToolResponse("Could not start a knowledge-base search.")
	}

	chunks, note := h.pollRetrieval(ctx, job.ID, tenantID)
	resp := map[string]any{"chunks": chunks}
	if note != "" {
		resp["note"] = note
	}
	return resp
}

// pollRetrieval waits for the rag job to finish, returning shaped chunks or a
// note explaining why none are available (budget block, failure, timeout).
func (h *Handler) pollRetrieval(ctx context.Context, jobID, tenantID uuid.UUID) ([]map[string]any, string) {
	deadline := time.Now().Add(retrievalTimeout)
	ticker := time.NewTicker(retrievalPoll)
	defer ticker.Stop()

	for {
		job, err := database.GetAIJob(ctx, h.db, jobID, tenantID)
		if err == nil {
			switch job.Status {
			case "succeeded":
				return shapeToolResponseChunks(parseRagResults(job.Result)), ""
			case "failed":
				return nil, "The knowledge-base search failed."
			case "needs_review":
				// Most commonly the tenant budget pre-flight blocked the job.
				return nil, "The knowledge base is unavailable right now (budget or review hold)."
			}
		}
		if time.Now().After(deadline) {
			return nil, "The knowledge-base search timed out."
		}
		select {
		case <-ctx.Done():
			return nil, "The session ended before the search finished."
		case <-ticker.C:
		}
	}
}

// ragResult mirrors the worker's ad-hoc rag job result (only the fields we
// surface to the model).
type ragResult struct {
	Results []ragChunk `json:"results"`
}

type ragChunk struct {
	ChunkID       string   `json:"chunk_id"`
	DocumentTitle string   `json:"document_title"`
	Text          string   `json:"text"`
	HeadingPath   []string `json:"heading_path"`
	SourcePage    *int     `json:"source_page"`
}

func parseRagResults(raw json.RawMessage) []ragChunk {
	if len(raw) == 0 {
		return nil
	}
	var r ragResult
	if err := json.Unmarshal(raw, &r); err != nil {
		return nil
	}
	return r.Results
}

// shapeToolResponseChunks is the pure transform from retrieved chunks to the
// tool-response payload: truncate long text, cap the count, keep only the
// fields the model needs to ground and cite an answer.
func shapeToolResponseChunks(chunks []ragChunk) []map[string]any {
	out := make([]map[string]any, 0, len(chunks))
	for _, c := range chunks {
		if len(out) >= maxToolChunks {
			break
		}
		text := c.Text
		if len(text) > maxToolChunkChars {
			text = text[:maxToolChunkChars] + "...[truncated]"
		}
		m := map[string]any{
			"chunk_id":       c.ChunkID,
			"document_title": c.DocumentTitle,
			"text":           text,
		}
		if len(c.HeadingPath) > 0 {
			m["heading_path"] = c.HeadingPath
		}
		if c.SourcePage != nil {
			m["source_page"] = *c.SourcePage
		}
		out = append(out, m)
	}
	return out
}

func emptyToolResponse(note string) map[string]any {
	return map[string]any{"chunks": []map[string]any{}, "note": note}
}

// hashQuery is a small stable hash for the idempotency-key suffix (mirrors the
// rag handler's hashQueryText: identical voice queries coalesce briefly).
func hashQuery(s string) uint64 {
	h := fnv.New64a()
	_, _ = h.Write([]byte(s))
	return h.Sum64()
}
