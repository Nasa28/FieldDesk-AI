"use client";

import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import {
  defaultWindow,
  formatMS,
  formatTimestamp,
  formatUSD,
  toRFC3339,
  type TimeWindow,
} from "../../lib/dashboard";

type FailureRow = {
  id: string;
  item_type: "model_call" | "job";
  job_id?: string;
  kind: string;
  provider?: string;
  model?: string;
  status: string;
  input_tokens: number;
  output_tokens: number;
  duration_ms: number;
  cost_usd: number;
  error_class?: string;
  error_message?: string;
  attempt_count?: number;
  max_attempts?: number;
  locked_by?: string;
  lease_expires_at?: string;
  request_meta?: Record<string, unknown>;
  response_meta?: Record<string, unknown>;
  created_at: string;
};

type ListResponse = {
  window: { from: string; to: string };
  items: FailureRow[];
  count: number;
  next_cursor: string;
};

const PAGE_LIMIT = 50;

export default function FailuresPage() {
  const [range, setRange] = useState<TimeWindow>(defaultWindow());
  const [kind, setKind] = useState("");
  const [provider, setProvider] = useState("");
  const [pages, setPages] = useState<FailureRow[][]>([]);
  const [nextCursor, setNextCursor] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function fetchPage(cursor: string) {
    const params = new URLSearchParams({
      from: toRFC3339(range.from),
      to: toRFC3339(range.to),
      limit: String(PAGE_LIMIT),
    });
    if (kind) params.set("kind", kind);
    if (provider) params.set("provider", provider);
    if (cursor) params.set("cursor", cursor);
    return api<ListResponse>(`/v1/admin/failures?${params}`);
  }

  async function load() {
    setLoading(true);
    setError("");
    try {
      const res = await fetchPage("");
      setPages([res.items]);
      setNextCursor(res.next_cursor || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load failures.");
    } finally {
      setLoading(false);
    }
  }

  async function loadMore() {
    if (!nextCursor) return;
    setLoading(true);
    setError("");
    try {
      const res = await fetchPage(nextCursor);
      setPages((prev) => [...prev, res.items]);
      setNextCursor(res.next_cursor || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load more.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const rows = pages.flat();
  const totalFailedCost = rows.reduce((sum, r) => sum + r.cost_usd, 0);

  return (
    <div>
      <h1 className="page-title">Failures</h1>
      <p className="page-subtitle">
        Failed provider calls plus failed, needs-review, and stuck jobs. Failed
        provider calls can still incur cost; the running total below sums what's
        loaded.
      </p>

      <div className="toolbar">
        <label className="field">
          <span>From</span>
          <input
            type="datetime-local"
            value={range.from}
            onChange={(e) => setRange({ ...range, from: e.target.value })}
          />
        </label>
        <label className="field">
          <span>To</span>
          <input
            type="datetime-local"
            value={range.to}
            onChange={(e) => setRange({ ...range, to: e.target.value })}
          />
        </label>
        <label className="field">
          <span>Kind</span>
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">All</option>
            <option value="transcription">transcription</option>
            <option value="llm">llm</option>
            <option value="embedding">embedding</option>
            <option value="rerank">rerank</option>
          </select>
        </label>
        <label className="field">
          <span>Provider</span>
          <input
            placeholder="e.g. openai"
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
          />
        </label>
        <button className="primary" disabled={loading} onClick={() => void load()}>
          {loading && pages.length === 0 ? "Loading…" : "Refresh"}
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      <div className="card">
        <div className="muted" style={{ fontSize: 12 }}>
          Failed cost (loaded rows)
        </div>
        <div style={{ fontSize: 24, fontWeight: 600, marginTop: 4, color: rows.length ? "#ff8f8f" : undefined }}>
          {formatUSD(totalFailedCost)}
        </div>
      </div>

      <div className="card" style={{ padding: 0 }}>
        <table className="table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Source</th>
              <th>Kind</th>
              <th>Provider / Model</th>
              <th>Status / Error</th>
              <th>Latency</th>
              <th>Cost</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && !loading && (
              <tr>
                <td colSpan={7} className="muted" style={{ padding: 16 }}>
                  No failures in this window. (That's good.)
                </td>
              </tr>
            )}
            {rows.map((row) => (
              <tr key={row.id}>
                <td className="muted">{formatTimestamp(row.created_at)}</td>
                <td>
                  <span className={row.item_type === "job" ? "pill error" : "pill"}>
                    {row.item_type === "job" ? "job" : "call"}
                  </span>
                </td>
                <td>{row.kind}</td>
                <td>
                  {row.provider || "—"}
                  <div className="muted" style={{ fontSize: 12 }}>{row.model || "—"}</div>
                </td>
                <td>
                  <span className="pill error">{row.status || row.error_class || "failed"}</span>
                  {row.error_message && (
                    <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                      {row.error_message}
                    </div>
                  )}
                  {jobDetail(row) && (
                    <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                      {jobDetail(row)}
                    </div>
                  )}
                </td>
                <td>{formatMS(row.duration_ms)}</td>
                <td>{formatUSD(row.cost_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="toolbar" style={{ marginTop: 12 }}>
        <span className="muted">{rows.length} row(s) loaded</span>
        <button
          disabled={!nextCursor || loading}
          onClick={() => void loadMore()}
        >
          {loading && pages.length > 0 ? "Loading…" : nextCursor ? "Load more" : "End of results"}
        </button>
      </div>
    </div>
  );
}

function jobDetail(row: FailureRow): string {
  if (row.item_type !== "job") return "";
  const parts: string[] = [];
  if (row.attempt_count !== undefined && row.max_attempts !== undefined) {
    parts.push(`attempts ${row.attempt_count}/${row.max_attempts}`);
  }
  const voiceNoteID = metaString(row.request_meta?.voice_note_id);
  const transcriptID = metaString(row.request_meta?.transcript_id);
  if (voiceNoteID) parts.push(`voice ${shortID(voiceNoteID)}`);
  if (transcriptID) parts.push(`transcript ${shortID(transcriptID)}`);
  if (row.lease_expires_at) parts.push(`lease ${formatTimestamp(row.lease_expires_at)}`);
  return parts.join(" | ");
}

function metaString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function shortID(id: string): string {
  return id.length > 8 ? id.slice(0, 8) : id;
}
