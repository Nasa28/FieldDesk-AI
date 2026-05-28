"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { formatUSD } from "../lib/dashboard";

type Budget = {
  tenant_id: string;
  daily_budget_usd?: number | null;
  monthly_budget_usd?: number | null;
  max_cost_per_ticket?: number | null;
  pause_on_exceeded: boolean;
  daily_spend_usd: number;
  monthly_spend_usd: number;
  daily_over: boolean;
  monthly_over: boolean;
};

// HTML number inputs round-trip strings, not numbers. Keeping editable state
// as strings lets an empty box mean "no cap" while "0" means "zero spend
// allowed" — both legitimate, but they round-trip to null vs. 0 respectively.
type BudgetForm = {
  daily_budget_usd: string;
  monthly_budget_usd: string;
  max_cost_per_ticket: string;
  pause_on_exceeded: boolean;
};

function toForm(b: Budget): BudgetForm {
  return {
    daily_budget_usd: b.daily_budget_usd == null ? "" : String(b.daily_budget_usd),
    monthly_budget_usd: b.monthly_budget_usd == null ? "" : String(b.monthly_budget_usd),
    max_cost_per_ticket: b.max_cost_per_ticket == null ? "" : String(b.max_cost_per_ticket),
    pause_on_exceeded: b.pause_on_exceeded,
  };
}

function parseLimit(raw: string): number | null | "invalid" {
  if (raw.trim() === "") return null;
  const n = Number(raw);
  if (!Number.isFinite(n) || n < 0) return "invalid";
  return n;
}

export function BudgetsCard({ tenantId }: { tenantId: string }) {
  const [budget, setBudget] = useState<Budget | null>(null);
  const [form, setForm] = useState<BudgetForm | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [savedAt, setSavedAt] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await api<Budget>("/v1/admin/budgets");
      setBudget(res);
      setForm(toForm(res));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load budgets.");
    } finally {
      setLoading(false);
    }
  }, []);

  const tenantConfigured = Boolean(tenantId.trim());

  useEffect(() => {
    if (!tenantConfigured) {
      setBudget(null);
      setForm(null);
      setError("");
      setSavedAt("");
      return;
    }
    void load();
  }, [tenantConfigured, tenantId, load]);

  async function save() {
    if (!form) return;
    const daily = parseLimit(form.daily_budget_usd);
    const monthly = parseLimit(form.monthly_budget_usd);
    const perTicket = parseLimit(form.max_cost_per_ticket);
    if (daily === "invalid" || monthly === "invalid" || perTicket === "invalid") {
      setError("Limits must be non-negative numbers, or blank for no cap.");
      return;
    }
    if (daily != null && monthly != null && daily > monthly) {
      setError("Daily cap cannot exceed monthly cap.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const res = await api<Budget>("/v1/admin/budgets", {
        method: "PUT",
        body: JSON.stringify({
          daily_budget_usd: daily,
          monthly_budget_usd: monthly,
          max_cost_per_ticket: perTicket,
          pause_on_exceeded: form.pause_on_exceeded,
        }),
      });
      setBudget(res);
      setForm(toForm(res));
      setSavedAt(new Date().toLocaleTimeString());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save budget.");
    } finally {
      setSaving(false);
    }
  }

  if (!tenantConfigured) {
    return (
      <div className="card">
        <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>
          Tenant AI budgets
        </div>
        <p className="muted">Set a tenant ID above to load budgets.</p>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="toolbar" style={{ marginBottom: 16 }}>
        <div style={{ flex: 1 }}>
          <div className="muted" style={{ fontSize: 12 }}>Tenant AI budgets</div>
          <div style={{ fontSize: 18, fontWeight: 600 }}>
            Daily / monthly caps + pause toggle
          </div>
        </div>
        <button onClick={() => void load()} disabled={loading || saving}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      {budget && (
        <div className="grid two" style={{ marginBottom: 16 }}>
          <SpendCell
            label="Today's spend"
            spend={budget.daily_spend_usd}
            cap={budget.daily_budget_usd}
            over={budget.daily_over}
          />
          <SpendCell
            label="Month-to-date spend"
            spend={budget.monthly_spend_usd}
            cap={budget.monthly_budget_usd}
            over={budget.monthly_over}
          />
        </div>
      )}

      {form && (
        <BudgetForm
          form={form}
          setForm={setForm}
          saving={saving}
          save={save}
          savedAt={savedAt}
        />
      )}
    </div>
  );
}

function BudgetForm({
  form,
  setForm,
  saving,
  save,
  savedAt,
}: {
  form: BudgetForm;
  setForm: (f: BudgetForm) => void;
  saving: boolean;
  save: () => void;
  savedAt: string;
}) {
  return (
    <>
      <div className="grid two">
        <label className="field">
          <span>Daily budget (USD, blank = no cap)</span>
          <input
            type="number"
            min="0"
            step="0.01"
            value={form.daily_budget_usd}
            onChange={(e) => setForm({ ...form, daily_budget_usd: e.target.value })}
          />
        </label>
        <label className="field">
          <span>Monthly budget (USD, blank = no cap)</span>
          <input
            type="number"
            min="0"
            step="0.01"
            value={form.monthly_budget_usd}
            onChange={(e) => setForm({ ...form, monthly_budget_usd: e.target.value })}
          />
        </label>
        <label className="field">
          <span>Max cost per ticket (USD, not yet enforced)</span>
          <input
            type="number"
            min="0"
            step="0.0001"
            value={form.max_cost_per_ticket}
            onChange={(e) => setForm({ ...form, max_cost_per_ticket: e.target.value })}
          />
        </label>
        <label className="field">
          <span>Pause on exceeded</span>
          <select
            value={form.pause_on_exceeded ? "true" : "false"}
            onChange={(e) =>
              setForm({ ...form, pause_on_exceeded: e.target.value === "true" })
            }
          >
            <option value="true">On — block new AI jobs when over</option>
            <option value="false">Off — keep spending past the cap</option>
          </select>
        </label>
      </div>

      <div className="toolbar" style={{ marginTop: 16 }}>
        <button className="primary" onClick={() => void save()} disabled={saving}>
          {saving ? "Saving…" : "Save budgets"}
        </button>
        {savedAt && <span className="muted">Saved at {savedAt}.</span>}
      </div>
    </>
  );
}

function SpendCell({
  label,
  spend,
  cap,
  over,
}: {
  label: string;
  spend: number;
  cap?: number | null;
  over: boolean;
}) {
  const pct = cap == null ? null : cap > 0 ? Math.min(100, (spend / cap) * 100) : over ? 100 : 0;
  const warn = pct != null && pct >= 80;
  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: 8,
        padding: 16,
        background: "#101318",
      }}
    >
      <div className="muted" style={{ fontSize: 12 }}>{label}</div>
      <div
        style={{
          fontSize: 22,
          fontWeight: 600,
          marginTop: 4,
          color: over ? "#ff8f8f" : undefined,
        }}
      >
        {formatUSD(spend)}
        {cap != null && (
          <span className="muted" style={{ fontSize: 14, fontWeight: 400 }}>
            {" "}
            / {formatUSD(cap)}
          </span>
        )}
      </div>
      {cap == null ? (
        <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
          No cap configured.
        </div>
      ) : (
        <div
          style={{
            marginTop: 8,
            height: 6,
            background: "#1b2027",
            borderRadius: 3,
            overflow: "hidden",
          }}
        >
          <div
            style={{
              width: `${pct ?? 0}%`,
              height: "100%",
              background: over ? "#ff8f8f" : warn ? "#f0b400" : "#3b82f6",
            }}
          />
        </div>
      )}
    </div>
  );
}
