"use client";

import { useEffect, useState } from "react";
import { api, currentTenantId, saveTenantId } from "../../lib/api";

type ReviewItem = {
  review: {
    id: string;
    reason: string;
    status: string;
    created_at: string;
  };
  transcript?: {
    preview: string;
  };
  extraction?: {
    parsed_output?: Record<string, unknown>;
    confidence?: number;
  };
};

function pretty(value: unknown) {
  return JSON.stringify(value ?? {}, null, 2);
}

export default function ReviewQueuePage() {
  const [tenantId, setTenantId] = useState("");
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    const stored = currentTenantId();
    setTenantId(stored);
    if (stored) {
      void load();
    }
  }, []);

  async function load() {
    setError("");
    if (tenantId.trim()) {
      saveTenantId(tenantId);
    }
    const res = await api<{ items: ReviewItem[] }>("/v1/review-queue?status=open&limit=50");
    setItems(res.items);
    setDrafts(Object.fromEntries(res.items.map((item) => [
      item.review.id,
      pretty(item.extraction?.parsed_output),
    ])));
  }

  async function resolve(id: string) {
    setBusy(id);
    setError("");
    try {
      const correction = JSON.parse(drafts[id] || "{}");
      await api(`/v1/review-queue/${id}/resolve`, {
        method: "POST",
        body: JSON.stringify({ correction, notes: notes[id] || undefined }),
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not resolve review.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div>
      <h1 className="page-title">Review Queue</h1>
      <div className="toolbar">
        <label className="field">
          <span>Tenant ID</span>
          <input value={tenantId} onChange={(e) => setTenantId(e.target.value)} />
        </label>
        <button disabled={!tenantId.trim()} onClick={() => void load()}>
          Refresh
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="stack">
        {items.map((item) => (
          <div className="card" key={item.review.id}>
            <div className="toolbar">
              <span className="pill">{item.review.reason}</span>
              <span className="muted">{item.review.id}</span>
              {item.extraction?.confidence != null && (
                <span className="muted">confidence {item.extraction.confidence}</span>
              )}
              <button className="primary" disabled={busy === item.review.id} onClick={() => void resolve(item.review.id)}>
                Resolve
              </button>
            </div>
            {item.transcript?.preview && <p>{item.transcript.preview}</p>}
            <label className="field">
              <span>Correction JSON</span>
              <textarea
                value={drafts[item.review.id] ?? "{}"}
                onChange={(e) => setDrafts((prev) => ({ ...prev, [item.review.id]: e.target.value }))}
              />
            </label>
            <label className="field" style={{ marginTop: 12 }}>
              <span>Notes</span>
              <input
                value={notes[item.review.id] ?? ""}
                onChange={(e) => setNotes((prev) => ({ ...prev, [item.review.id]: e.target.value }))}
              />
            </label>
          </div>
        ))}
        {items.length === 0 && <div className="card muted">No open reviews.</div>}
      </div>
    </div>
  );
}
