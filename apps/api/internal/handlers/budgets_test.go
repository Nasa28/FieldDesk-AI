package handlers

import (
	"math"
	"strings"
	"testing"
)

func ptr[T any](v T) *T { return &v }

func TestValidateBudgetPayloadAcceptsNilLimits(t *testing.T) {
	if err := validateBudgetPayload(budgetPayload{}); err != nil {
		t.Fatalf("nil-everywhere payload should validate, got %v", err)
	}
}

func TestValidateBudgetPayloadAcceptsZero(t *testing.T) {
	// Zero is a valid cap — means "no spend allowed today." Operator's call.
	if err := validateBudgetPayload(budgetPayload{DailyBudgetUSD: ptr(0.0)}); err != nil {
		t.Fatalf("zero daily cap should validate, got %v", err)
	}
}

func TestValidateBudgetPayloadRejectsNegative(t *testing.T) {
	cases := []budgetPayload{
		{DailyBudgetUSD: ptr(-1.0)},
		{MonthlyBudgetUSD: ptr(-0.01)},
		{MaxCostPerTicket: ptr(-100.0)},
	}
	for i, c := range cases {
		err := validateBudgetPayload(c)
		if err == nil || !strings.Contains(err.Error(), "negative") {
			t.Errorf("case %d: expected negative-value rejection, got %v", i, err)
		}
	}
}

func TestValidateBudgetPayloadRejectsNonFinite(t *testing.T) {
	cases := []budgetPayload{
		{DailyBudgetUSD: ptr(math.NaN())},
		{MonthlyBudgetUSD: ptr(math.Inf(1))},
		{MaxCostPerTicket: ptr(math.Inf(-1))},
	}
	for i, c := range cases {
		err := validateBudgetPayload(c)
		if err == nil || !strings.Contains(err.Error(), "finite") {
			t.Errorf("case %d: expected finite-value rejection, got %v", i, err)
		}
	}
}

func TestValidateBudgetPayloadRejectsDailyOverMonthly(t *testing.T) {
	// A daily cap above the monthly cap would never bind — almost certainly
	// a typo. Reject before the bad number reaches the DB.
	err := validateBudgetPayload(budgetPayload{
		DailyBudgetUSD:   ptr(50.0),
		MonthlyBudgetUSD: ptr(10.0),
	})
	if err == nil || !strings.Contains(err.Error(), "cannot exceed") {
		t.Fatalf("expected daily>monthly rejection, got %v", err)
	}
}

func TestValidateBudgetPayloadAcceptsEqualDailyAndMonthly(t *testing.T) {
	// Equal is fine: a one-day budget is a legitimate config.
	err := validateBudgetPayload(budgetPayload{
		DailyBudgetUSD:   ptr(10.0),
		MonthlyBudgetUSD: ptr(10.0),
	})
	if err != nil {
		t.Fatalf("equal daily and monthly should validate, got %v", err)
	}
}

func TestValidateBudgetPayloadAcceptsPauseToggle(t *testing.T) {
	for _, v := range []bool{true, false} {
		err := validateBudgetPayload(budgetPayload{PauseOnExceeded: ptr(v)})
		if err != nil {
			t.Fatalf("pause_on_exceeded=%v should validate, got %v", v, err)
		}
	}
}
