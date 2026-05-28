package database

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestHumanReviewJSONFieldsMarshalAsObjects(t *testing.T) {
	body, err := json.Marshal(ReviewQueueItem{
		Review: HumanReview{
			Correction: json.RawMessage(`{"issue_summary":"fixed"}`),
		},
		Extraction: &ExtractionSummary{
			ParsedOutput: json.RawMessage(`{"confidence":0.9}`),
		},
	})
	if err != nil {
		t.Fatalf("marshal review queue item: %v", err)
	}
	got := string(body)
	if !strings.Contains(got, `"correction":{"issue_summary":"fixed"}`) {
		t.Fatalf("correction was not emitted as JSON object: %s", got)
	}
	if !strings.Contains(got, `"parsed_output":{"confidence":0.9}`) {
		t.Fatalf("parsed_output was not emitted as JSON object: %s", got)
	}
}

func TestTicketCorrectionPatchAndSeedValidation(t *testing.T) {
	if (TicketCorrection{}).HasPatchField() {
		t.Fatal("empty correction should not be a patch")
	}
	if (TicketCorrection{}).HasTicketSeedField() {
		t.Fatal("empty correction should not seed a ticket")
	}
	blank := "   "
	if (TicketCorrection{IssueSummary: &blank}).HasPatchField() {
		t.Fatal("blank string correction should not be a patch")
	}
	summary := "Leaking water heater"
	if !(TicketCorrection{IssueSummary: &summary}).HasPatchField() {
		t.Fatal("issue summary should be a patch")
	}
	if !(TicketCorrection{IssueSummary: &summary}).HasTicketSeedField() {
		t.Fatal("issue summary should seed a ticket")
	}
	values := []string{"", "plumbing"}
	if !(TicketCorrection{RequiredSkills: &values}).HasPatchField() {
		t.Fatal("non-empty slice value should be a patch")
	}
	if !(TicketCorrection{RequiredSkills: &values}).HasTicketSeedField() {
		t.Fatal("non-empty slice value should seed a ticket")
	}
	emptyValues := []string{}
	if !(TicketCorrection{RequiredSkills: &emptyValues}).HasPatchField() {
		t.Fatal("explicit empty slice should be a valid patch")
	}
	if (TicketCorrection{RequiredSkills: &emptyValues}).HasTicketSeedField() {
		t.Fatal("empty slice alone should not seed a ticket")
	}
	warrantyFalse := false
	if !(TicketCorrection{WarrantyMentioned: &warrantyFalse}).HasPatchField() {
		t.Fatal("false boolean should be a valid patch")
	}
	if (TicketCorrection{WarrantyMentioned: &warrantyFalse}).HasTicketSeedField() {
		t.Fatal("boolean alone should not seed a new ticket")
	}
}

func TestTicketCorrectionSliceArgsPreserveOmittedAndAllowExplicitClear(t *testing.T) {
	var omitted *[]string
	if stringSliceArg(omitted) != nil {
		t.Fatal("omitted slice should pass nil so SQL preserves existing value")
	}
	clear := []string{}
	arg := stringSliceArg(&clear)
	if arg == nil {
		t.Fatal("explicit empty slice should be passed so SQL can clear existing value")
	}
	if got := stringSliceOrEmpty(omitted); len(got) != 0 {
		t.Fatalf("omitted slice should insert as empty slice, got %#v", got)
	}
}
