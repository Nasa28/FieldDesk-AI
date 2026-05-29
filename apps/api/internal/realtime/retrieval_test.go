package realtime

import (
	"strings"
	"testing"
)

func TestShapeToolResponseChunksTruncatesAndCaps(t *testing.T) {
	page := 4
	chunks := make([]ragChunk, 0, 12)
	for i := 0; i < 12; i++ {
		chunks = append(chunks, ragChunk{
			ChunkID:       "c",
			DocumentTitle: "Pump Manual",
			Text:          strings.Repeat("x", maxToolChunkChars+500),
			HeadingPath:   []string{"Entry", "Pre-checks"},
			SourcePage:    &page,
		})
	}

	out := shapeToolResponseChunks(chunks)
	if len(out) != maxToolChunks {
		t.Fatalf("got %d chunks, want cap %d", len(out), maxToolChunks)
	}
	text := out[0]["text"].(string)
	if !strings.HasSuffix(text, "...[truncated]") {
		t.Errorf("long text not truncated: ...%q", text[len(text)-20:])
	}
	if out[0]["document_title"] != "Pump Manual" {
		t.Errorf("document_title = %v", out[0]["document_title"])
	}
	if out[0]["source_page"] != 4 {
		t.Errorf("source_page = %v, want 4", out[0]["source_page"])
	}
	if hp, ok := out[0]["heading_path"].([]string); !ok || len(hp) != 2 {
		t.Errorf("heading_path = %v", out[0]["heading_path"])
	}
}

func TestShapeToolResponseChunksOmitsEmptyOptionals(t *testing.T) {
	out := shapeToolResponseChunks([]ragChunk{{ChunkID: "c", DocumentTitle: "Doc", Text: "short"}})
	if len(out) != 1 {
		t.Fatalf("want 1 chunk, got %d", len(out))
	}
	if _, ok := out[0]["source_page"]; ok {
		t.Error("nil source_page should be omitted")
	}
	if _, ok := out[0]["heading_path"]; ok {
		t.Error("empty heading_path should be omitted")
	}
}

func TestParseRagResults(t *testing.T) {
	raw := []byte(`{"results":[{"chunk_id":"a","document_title":"D","text":"t","source_page":2}]}`)
	got := parseRagResults(raw)
	if len(got) != 1 || got[0].ChunkID != "a" || got[0].SourcePage == nil || *got[0].SourcePage != 2 {
		t.Fatalf("parseRagResults = %+v", got)
	}
	if parseRagResults(nil) != nil {
		t.Error("nil raw should yield nil")
	}
	if parseRagResults([]byte(`not json`)) != nil {
		t.Error("invalid json should yield nil")
	}
}

func TestEmptyToolResponseShape(t *testing.T) {
	resp := emptyToolResponse("nope")
	chunks, ok := resp["chunks"].([]map[string]any)
	if !ok || len(chunks) != 0 {
		t.Errorf("expected empty chunks slice, got %v", resp["chunks"])
	}
	if resp["note"] != "nope" {
		t.Errorf("note = %v", resp["note"])
	}
}
