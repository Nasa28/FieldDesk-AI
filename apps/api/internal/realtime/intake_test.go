package realtime

import "testing"

func TestIntakeAccumulatorLabelsDialogue(t *testing.T) {
	a := &intakeAccumulator{}
	a.add("ai", "What's the issue?")
	a.add("user", "water heater")
	a.add("user", " is leaking") // same speaker turn joins without a new label
	a.add("ai", "What's the address?")
	a.add("user", "14 Oak Street")

	got := a.transcript()
	want := "Dispatcher: What's the issue?\n" +
		"Technician: water heater is leaking\n" +
		"Dispatcher: What's the address?\n" +
		"Technician: 14 Oak Street"
	if got != want {
		t.Errorf("transcript =\n%q\nwant\n%q", got, want)
	}
}

func TestIntakeAccumulatorFirstTurnNoLeadingNewline(t *testing.T) {
	a := &intakeAccumulator{}
	a.add("ai", "Hi there")
	if got := a.transcript(); got != "Dispatcher: Hi there" {
		t.Errorf("transcript = %q, want %q", got, "Dispatcher: Hi there")
	}
}

func TestIntakeAccumulatorBoundaryForcesNewSameSpeakerTurn(t *testing.T) {
	a := &intakeAccumulator{}
	a.add("user", "first answer")
	a.markBoundary()
	a.add("user", "second answer")

	got := a.transcript()
	want := "Technician: first answer\nTechnician: second answer"
	if got != want {
		t.Errorf("transcript = %q, want %q", got, want)
	}
}

func TestIntakeAccumulatorClaimFinishOnce(t *testing.T) {
	a := &intakeAccumulator{}
	if !a.claimFinish() {
		t.Fatal("first claimFinish should return true")
	}
	if a.claimFinish() {
		t.Error("second claimFinish should return false (no double-file)")
	}
}
