"use client";

import { useEffect, useState } from "react";
import { BudgetsCard } from "../../components/budgets-card";
import { currentTenantId, saveTenantId } from "../../lib/api";

export default function SettingsPage() {
  const [tenantId, setTenantId] = useState("");
  const [savedTenantId, setSavedTenantId] = useState("");
  const [saved, setSaved] = useState<"" | "ok" | "cleared">("");

  useEffect(() => {
    const current = currentTenantId();
    setTenantId(current);
    setSavedTenantId(current);
  }, []);

  function persist() {
    const trimmed = tenantId.trim();
    saveTenantId(trimmed);
    setTenantId(trimmed);
    setSavedTenantId(trimmed);
    setSaved("ok");
  }

  function clear() {
    if (typeof window === "undefined") return;
    window.localStorage.removeItem("fielddesk.tenant_id");
    setTenantId("");
    setSavedTenantId("");
    setSaved("cleared");
  }

  const apiUrl =
    (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_URL) ||
    "http://localhost:8080";

  return (
    <div>
      <h1 className="page-title">Settings</h1>
      <p className="page-subtitle">
        Real auth is not yet wired; until then the dashboard authenticates by
        sending an <code>X-Tenant-ID</code> header on every request. Set it
        here once and it persists in <code>localStorage</code>.
      </p>

      <div className="card">
        <div className="toolbar">
          <label className="field" style={{ minWidth: 360 }}>
            <span>Tenant ID</span>
            <input
              placeholder="UUID from ./scripts/seed.sh"
              value={tenantId}
              onChange={(e) => {
                setTenantId(e.target.value);
                setSaved("");
              }}
            />
          </label>
          <button
            className="primary"
            disabled={!tenantId.trim()}
            onClick={persist}
          >
            Save
          </button>
          <button onClick={clear} disabled={!tenantId}>
            Clear
          </button>
        </div>
        {saved === "ok" && <p className="muted">Saved.</p>}
        {saved === "cleared" && <p className="muted">Cleared.</p>}
      </div>

      <div className="card">
        <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>
          API base URL
        </div>
        <div>{apiUrl}</div>
        <div className="muted" style={{ fontSize: 12, marginTop: 12 }}>
          Override with <code>NEXT_PUBLIC_API_URL</code> at build time.
        </div>
      </div>

      <BudgetsCard tenantId={savedTenantId} />

      <div className="card">
        <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>
          Deferred to a later slice
        </div>
        <ul style={{ margin: 0, paddingLeft: 20 }}>
          <li>Email/password sign-in (Phase 1.5 cleanup).</li>
          <li>
            <code>max_cost_per_ticket</code> enforcement — accepted by the API,
            not yet checked at runtime (needs the JSONB denormalization).
          </li>
          <li>Provider routing / model preferences.</li>
        </ul>
      </div>
    </div>
  );
}
