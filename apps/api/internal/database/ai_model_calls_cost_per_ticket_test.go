package database

import (
	"strings"
	"testing"
)

// SQL-shape tests for the per-ticket cost aggregation. We don't run these
// queries against a real Postgres here — the rest of the database package
// tests the same way (see recommendations_test.go). What we DO want locked
// down are the invariants that, if quietly dropped, would silently leak
// data across tenants or skew the average. Each test asserts exactly one
// invariant so a regression points at the right line.

func TestMostExpensiveTicketsSQLJoinsOnTenantAndTicket(t *testing.T) {
	// The join must scope on BOTH jt.id = amc.ticket_id AND
	// jt.tenant_id = amc.tenant_id. If only the first is present, a
	// (tenant-a, ticket-X) ai_model_calls row could JOIN to a
	// (tenant-b, ticket-X) job_ticket if ticket UUIDs ever collide. They
	// shouldn't — but defense-in-depth here is cheap.
	if !strings.Contains(mostExpensiveTicketsSQL, "jt.id = amc.ticket_id") {
		t.Fatalf("most-expensive-tickets join must bind jt.id to amc.ticket_id")
	}
	if !strings.Contains(mostExpensiveTicketsSQL, "jt.tenant_id = amc.tenant_id") {
		t.Fatalf("most-expensive-tickets join must scope to amc.tenant_id")
	}
}

func TestMostExpensiveTicketsSQLOrdersByCostDescending(t *testing.T) {
	// "Most expensive" is the whole point. If someone re-orders the
	// columns and the ORDER BY ends up pointing at a different SUM, the
	// endpoint silently surfaces the wrong list.
	if !strings.Contains(mostExpensiveTicketsSQL, "ORDER BY SUM(amc.cost_usd) DESC") {
		t.Fatalf("most-expensive-tickets must ORDER BY SUM(cost_usd) DESC")
	}
}

func TestMostExpensiveTicketsSQLFiltersByTenantInWhere(t *testing.T) {
	// Belt: the JOIN already filters on tenant; the WHERE clause filters
	// again so the planner picks the tenant_id index even if the JOIN
	// rewrite were to change.
	if !strings.Contains(mostExpensiveTicketsSQL, "WHERE amc.tenant_id = $1") {
		t.Fatalf("most-expensive-tickets must filter amc.tenant_id in WHERE")
	}
}

func TestCostPerTicketSummarySQLExcludesNullTicketRows(t *testing.T) {
	// The average is "per attributed ticket." Transcription calls that
	// pre-date back-stamping (and never paired with a ticket because the
	// extraction needs_review'd) land with ticket_id = NULL. Including
	// them would lump their cost under a phantom "ticket" and skew the
	// COUNT and AVG. Guard the IS NOT NULL filter.
	if !strings.Contains(costPerTicketSummarySQL, "amc.ticket_id IS NOT NULL") {
		t.Fatalf("cost-per-ticket summary must exclude ticket_id IS NULL rows")
	}
}

func TestCostPerTicketSummarySQLGroupsPerTicketBeforeAveraging(t *testing.T) {
	// The CTE must GROUP BY ticket_id and then AVG over those sums.
	// If someone collapses the CTE into a flat AVG(cost_usd), the result
	// becomes "avg cost per call" — completely different number.
	if !strings.Contains(costPerTicketSummarySQL, "GROUP BY amc.ticket_id") {
		t.Fatalf("cost-per-ticket summary must GROUP BY ticket_id in the CTE")
	}
	if !strings.Contains(costPerTicketSummarySQL, "AVG(total)") {
		t.Fatalf("cost-per-ticket summary must AVG over per-ticket totals, not per-call costs")
	}
}
