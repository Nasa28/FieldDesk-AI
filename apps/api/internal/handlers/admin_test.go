package handlers

import (
	"testing"
	"time"
)

func TestParseWindowDefaultsToLastSevenDays(t *testing.T) {
	before := time.Now().UTC()
	w, err := parseWindow(map[string][]string{})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	after := time.Now().UTC()

	if !w.End.After(before.Add(-time.Second)) || !w.End.Before(after.Add(time.Second)) {
		t.Fatalf("end %v should sit between %v and %v", w.End, before, after)
	}
	span := w.End.Sub(w.Start)
	if span < 7*24*time.Hour-time.Minute || span > 7*24*time.Hour+time.Minute {
		t.Fatalf("default span should be ~7 days, got %v", span)
	}
}

func TestParseWindowHonorsFromAndTo(t *testing.T) {
	from := "2026-01-01T00:00:00Z"
	to := "2026-01-08T00:00:00Z"
	w, err := parseWindow(map[string][]string{"from": {from}, "to": {to}})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if w.Start.Format(time.RFC3339) != from {
		t.Fatalf("start = %v, want %v", w.Start.Format(time.RFC3339), from)
	}
	if w.End.Format(time.RFC3339) != to {
		t.Fatalf("end = %v, want %v", w.End.Format(time.RFC3339), to)
	}
}

func TestParseWindowRejectsInvertedRange(t *testing.T) {
	_, err := parseWindow(map[string][]string{
		"from": {"2026-02-01T00:00:00Z"},
		"to":   {"2026-01-01T00:00:00Z"},
	})
	if err == nil {
		t.Fatal("expected error when from > to")
	}
}

func TestParseWindowRejectsEqualBounds(t *testing.T) {
	_, err := parseWindow(map[string][]string{
		"from": {"2026-01-01T00:00:00Z"},
		"to":   {"2026-01-01T00:00:00Z"},
	})
	if err == nil {
		t.Fatal("expected error when from == to (empty window)")
	}
}

func TestParseWindowRejectsOverlongLookback(t *testing.T) {
	_, err := parseWindow(map[string][]string{
		"from": {"2020-01-01T00:00:00Z"},
		"to":   {"2026-01-01T00:00:00Z"},
	})
	if err == nil {
		t.Fatal("expected error when range exceeds 366 days")
	}
}

func TestParseWindowRejectsMalformedTimestamp(t *testing.T) {
	_, err := parseWindow(map[string][]string{"from": {"not-a-time"}})
	if err == nil {
		t.Fatal("expected error on unparseable from")
	}
	_, err = parseWindow(map[string][]string{"to": {"2026-01"}})
	if err == nil {
		t.Fatal("expected error on unparseable to")
	}
}

func TestRatioReturnsZeroWhenDenominatorZero(t *testing.T) {
	if got := ratio(0, 0); got != 0 {
		t.Fatalf("ratio(0,0) = %v, want 0", got)
	}
	if got := ratio(5, 0); got != 0 {
		t.Fatalf("ratio(5,0) should be 0 (no signal), got %v", got)
	}
}

func TestRatioComputesFraction(t *testing.T) {
	cases := []struct {
		n, d int64
		want float64
	}{
		{1, 4, 0.25},
		{3, 3, 1.0},
		{0, 10, 0.0},
		{9, 10, 0.9},
	}
	for _, c := range cases {
		got := ratio(c.n, c.d)
		if got != c.want {
			t.Errorf("ratio(%d,%d) = %v, want %v", c.n, c.d, got, c.want)
		}
	}
}

func TestParseCursorEmptyReturnsNil(t *testing.T) {
	got, err := parseCursor("")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != nil {
		t.Fatalf("empty cursor should return nil, got %v", got)
	}
}

func TestParseCursorAcceptsRFC3339AndNano(t *testing.T) {
	plain := "2026-01-01T12:00:00Z"
	if _, err := parseCursor(plain); err != nil {
		t.Fatalf("plain RFC3339 should parse: %v", err)
	}
	nano := "2026-01-01T12:00:00.123456789Z"
	if _, err := parseCursor(nano); err != nil {
		t.Fatalf("RFC3339Nano should parse: %v", err)
	}
}

func TestParseCursorRejectsGarbage(t *testing.T) {
	if _, err := parseCursor("not-a-timestamp"); err == nil {
		t.Fatal("expected error on garbage cursor")
	}
}
