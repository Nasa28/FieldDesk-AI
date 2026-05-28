package database

import (
	"testing"

	"github.com/google/uuid"
)

// Pure-function tests for the recommendations view. The DB join itself is
// exercised in integration-only flows; what we test here is the in-Go
// citation enrichment + synthesis-output unmarshal — the slices most likely
// to regress if someone touches the wire shape.

func TestEnrichCitationsDropsHallucinatedChunkIDs(t *testing.T) {
	docID := uuid.New()
	ragResults := []byte(`[
		{
			"chunk_id": "legit-1",
			"document_id": "` + docID.String() + `",
			"document_title": "Tankless Water Heater — Service Manual",
			"heading_path": ["Diagnostics", "Leaks"],
			"source_page": 12
		}
	]`)
	citations := []EnrichedCitation{
		{ChunkID: "legit-1"},
		{ChunkID: "hallucinated-zzz"},
	}

	got := enrichCitations(citations, ragResults)
	if len(got) != 1 {
		t.Fatalf("expected hallucinated chunk dropped, got %d citations", len(got))
	}
	c := got[0]
	if c.ChunkID != "legit-1" {
		t.Fatalf("wrong chunk_id kept: %q", c.ChunkID)
	}
	if c.DocumentTitle == nil || *c.DocumentTitle != "Tankless Water Heater — Service Manual" {
		t.Fatalf("expected enriched title, got %+v", c.DocumentTitle)
	}
	if c.DocumentID == nil || *c.DocumentID != docID {
		t.Fatalf("expected enriched document_id %s, got %+v", docID, c.DocumentID)
	}
	if len(c.HeadingPath) != 2 || c.HeadingPath[1] != "Leaks" {
		t.Fatalf("expected heading_path enriched, got %v", c.HeadingPath)
	}
	if c.SourcePage == nil || *c.SourcePage != 12 {
		t.Fatalf("expected source_page=12, got %+v", c.SourcePage)
	}
}

func TestEnrichCitationsWithNoRagResultsDropsEverything(t *testing.T) {
	// When the worker short-circuited zero-chunk synthesis, there's no
	// rag_queries row to join. Any citation the model somehow emitted is
	// unsourced by definition — drop them rather than render unattributed.
	citations := []EnrichedCitation{
		{ChunkID: "should-not-survive"},
	}
	got := enrichCitations(citations, nil)
	if len(got) != 0 {
		t.Fatalf("expected all citations dropped when no rag results, got %d", len(got))
	}
}

func TestEnrichCitationsPreservesNoteAndOrderForLegitChunks(t *testing.T) {
	docID := uuid.New()
	ragResults := []byte(`[
		{"chunk_id": "a", "document_id": "` + docID.String() + `", "document_title": "A", "heading_path": []},
		{"chunk_id": "b", "document_id": "` + docID.String() + `", "document_title": "B", "heading_path": []}
	]`)
	note := "supports the diagnosis"
	citations := []EnrichedCitation{
		{ChunkID: "b", Note: &note},
		{ChunkID: "a"},
	}
	got := enrichCitations(citations, ragResults)
	if len(got) != 2 {
		t.Fatalf("expected 2 citations, got %d", len(got))
	}
	// Order must follow the model's emission order — the synthesis prompt
	// asks the model to cite in order of supporting weight, so a re-sort
	// would lie about provenance.
	if got[0].ChunkID != "b" || got[1].ChunkID != "a" {
		t.Fatalf("citation order changed: %v", []string{got[0].ChunkID, got[1].ChunkID})
	}
	if got[0].Note == nil || *got[0].Note != note {
		t.Fatalf("note dropped during enrichment: %+v", got[0].Note)
	}
}

func TestApplySynthesisOutputFlattensFields(t *testing.T) {
	raw := []byte(`{
		"possible_diagnosis": "Worn supply hose",
		"suggested_parts": ["copper p-trap"],
		"safety_checklist": ["confirm shutoff"],
		"follow_up_questions": ["when did it start?"],
		"citations": [{"chunk_id": "a", "note": "n"}],
		"confidence": 0.71,
		"insufficient_context": false,
		"notes": null
	}`)
	view := &TicketRecommendation{
		SuggestedParts:    []string{},
		SafetyChecklist:   []string{},
		FollowUpQuestions: []string{},
		Citations:         []EnrichedCitation{},
	}
	if err := applySynthesisOutput(view, raw, nil); err != nil {
		t.Fatalf("unmarshal failed: %v", err)
	}
	if view.PossibleDiagnosis == nil || *view.PossibleDiagnosis != "Worn supply hose" {
		t.Fatalf("possible_diagnosis not flattened: %+v", view.PossibleDiagnosis)
	}
	if len(view.SuggestedParts) != 1 || view.SuggestedParts[0] != "copper p-trap" {
		t.Fatalf("suggested_parts not flattened: %v", view.SuggestedParts)
	}
	if view.Confidence != 0.71 {
		t.Fatalf("confidence not flattened: %v", view.Confidence)
	}
	if view.InsufficientContext {
		t.Fatalf("insufficient_context should be false")
	}
	if len(view.Citations) != 1 || view.Citations[0].ChunkID != "a" {
		t.Fatalf("citations not flattened: %v", view.Citations)
	}
}

func TestApplySynthesisOutputZeroBlobConfidenceFallsBackToRowColumn(t *testing.T) {
	// The worker writes 0.0 in the blob for degraded outputs (bad JSON
	// from the model). If the row column has a non-zero confidence, prefer
	// it — otherwise the operator sees "confidence 0.00" when the truth is
	// "we don't have a clean number from the model."
	raw := []byte(`{
		"possible_diagnosis": null,
		"suggested_parts": [],
		"safety_checklist": [],
		"follow_up_questions": [],
		"citations": [],
		"confidence": 0,
		"insufficient_context": true,
		"notes": "thin context"
	}`)
	rowConf := 0.42
	view := &TicketRecommendation{}
	if err := applySynthesisOutput(view, raw, &rowConf); err != nil {
		t.Fatalf("unmarshal failed: %v", err)
	}
	if view.Confidence != 0.42 {
		t.Fatalf("expected row-column fallback for zero blob confidence, got %v", view.Confidence)
	}
}

func TestApplySynthesisOutputBadJSONReturnsErrorAndUsesRowConfidence(t *testing.T) {
	rowConf := 0.55
	view := &TicketRecommendation{}
	err := applySynthesisOutput(view, []byte(`{not json`), &rowConf)
	if err == nil {
		t.Fatalf("expected unmarshal error on bad JSON")
	}
	if view.Confidence != 0.55 {
		t.Fatalf("expected row confidence preserved on unmarshal failure, got %v", view.Confidence)
	}
}

func TestBuildChunkLookupSkipsRowsWithoutChunkID(t *testing.T) {
	docID := uuid.New()
	raw := []byte(`[
		{"chunk_id": "", "document_id": "` + docID.String() + `", "document_title": "blank"},
		{"chunk_id": "ok", "document_id": "` + docID.String() + `", "document_title": "ok"}
	]`)
	got := buildChunkLookup(raw)
	if _, ok := got[""]; ok {
		t.Fatalf("empty chunk_id should not become a lookup key")
	}
	if _, ok := got["ok"]; !ok {
		t.Fatalf("expected 'ok' in lookup, got keys %v", keysOf(got))
	}
}

func keysOf(m map[string]chunkRef) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	return out
}
