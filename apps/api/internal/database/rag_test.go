package database

import (
	"strings"
	"testing"
)

func TestFormatHalfvecLiteralProducesParseableForm(t *testing.T) {
	got := formatHalfvecLiteral([]float32{0.1, -0.2, 1e-6})
	if !strings.HasPrefix(got, "[") || !strings.HasSuffix(got, "]") {
		t.Fatalf("expected bracketed literal, got %q", got)
	}
	// pgvector refuses scientific notation, so 1e-6 must render as a plain
	// decimal. The %.7f formatter satisfies this; verifying here so a
	// future regression that switches to %g surfaces in tests, not at
	// query time.
	if strings.Contains(got, "e") {
		t.Fatalf("literal must not contain scientific notation: %q", got)
	}
}

func TestFormatHalfvecLiteralEmptyVector(t *testing.T) {
	if got := formatHalfvecLiteral(nil); got != "[]" {
		t.Fatalf("empty vector should be [], got %q", got)
	}
}

func TestFormatHalfvecLiteralRoundTripsDimensions(t *testing.T) {
	vec := make([]float32, 1536)
	for i := range vec {
		vec[i] = float32(i) / 1536.0
	}
	got := formatHalfvecLiteral(vec)
	// Comma count = dims - 1 (one comma between each value).
	if commas := strings.Count(got, ","); commas != 1535 {
		t.Fatalf("expected 1535 commas for a 1536-dim vec, got %d", commas)
	}
}
