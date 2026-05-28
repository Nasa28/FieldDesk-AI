"use client";

import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import {
  defaultWindow,
  formatInt,
  formatMS,
  formatTimestamp,
  formatUSD,
  toRFC3339,
  type TimeWindow,
} from "../../lib/dashboard";

type ModelCallRow = {
  id: string;
  job_id?: string;
  kind: string;
  provider: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  duration_ms: number;
  cost_usd: number;
  success: boolean;
  error_class?: string;
  error_message?: string;
  request_meta?: Record<string, unknown>;
  response_meta?: Record<string, unknown>;
  created_at: string;
};

type ListResponse = {
  window: { from: string; to: string };
  items: ModelCallRow[];
  count: number;
  next_cursor: string;
};

const PAGE_LIMIT = 50;

export default function AILogsPage() {
  const [range, setRange] = useState<TimeWindow>(defaultWindow());
  const [kind, setKind] = useState("");
  const [provider, setProvider] = useState("");
  const [successFilter, setSuccessFilter] = useState("all");
  const [pages, setPages] = useState<ModelCallRow[][]>([]);
  const [nextCursor, setNextCursor] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function fetchPage(cursor: string) {
    const params = new URLSearchParams({
      from: toRFC3339(range.from),
      to: toRFC3339(range.to),
      limit: String(PAGE_LIMIT),
      success: successFilter,
    });
    if (kind) params.set("kind", kind);
    if (provider) params.set("provider", provider);
    if (cursor) params.set("cursor", cursor);
    return api<ListResponse>(`/v1/model-logs?${params}`);
  }

  async function load() {
    setLoading(true);
    setError("");
    try {
      const res = await fetchPage("");
      setPages([res.items]);
      setNextCursor(res.next_cursor || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load model logs.");
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

  return (
    <div>
      <h1 className="page-title">AI Logs</h1>
      <p className="page-subtitle">
        Every <code>ai_model_calls</code> row. Cursor-paginated with an opaque
        cursor; filters narrow the window without changing it.
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
        <label className="field">
          <span>Success</span>
          <select
            value={successFilter}
            onChange={(e) => setSuccessFilter(e.target.value)}
          >
            <option value="all">All</option>
            <option value="success">Successful only</option>
            <option value="failed">Failed only</option>
          </select>
        </label>
        <button className="primary" disabled={loading} onClick={() => void load()}>
          {loading && pages.length === 0 ? "Loading…" : "Refresh"}
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      <div className="card" style={{ padding: 0 }}>
        <table className="table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Kind</th>
              <th>Provider / Model</th>
              <th>Tokens (in / out)</th>
              <th>Latency</th>
              <th>Cost</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && !loading && (
              <tr>
                <td colSpan={7} className="muted" style={{ padding: 16 }}>
                  No model calls in this window.
                </td>
              </tr>
            )}
            {rows.map((row) => (
              <tr key={row.id}>
                <td className="muted">{formatTimestamp(row.created_at)}</td>
                <td>{row.kind}</td>
                <td>
                  {row.provider}
                  <div className="muted" style={{ fontSize: 12 }}>{row.model}</div>
                </td>
                <td>
                  {formatInt(row.input_tokens)} / {formatInt(row.output_tokens)}
                </td>
                <td>{formatMS(row.duration_ms)}</td>
                <td>{formatUSD(row.cost_usd)}</td>
                <td>
                  {row.success ? (
                    <span className="pill">ok</span>
                  ) : (
                    <span className="pill error">
                      {row.error_class || "failed"}
                    </span>
                  )}
                  {!row.success && row.error_message && (
                    <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                      {row.error_message}
                    </div>
                  )}
                  {metaSummary(row) && (
                    <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                      {metaSummary(row)}
                    </div>
                  )}
                </td>
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

function metaSummary(row: ModelCallRow): string {
  const parts: string[] = [];
  const request = row.request_meta ?? {};
  const response = row.response_meta ?? {};
  const voiceNoteID = metaString(request.voice_note_id);
  const transcriptID = metaString(request.transcript_id);
  const reviewReason = metaString(response.review_reason);
  const confidence = metaNumber(response.confidence);
  const jsonValid = metaBool(response.json_valid);

  if (voiceNoteID) parts.push(`voice ${shortID(voiceNoteID)}`);
  if (transcriptID) parts.push(`transcript ${shortID(transcriptID)}`);
  if (reviewReason) parts.push(`review ${reviewReason}`);
  if (confidence !== null) parts.push(`confidence ${confidence.toFixed(2)}`);
  if (jsonValid !== null) parts.push(`json ${jsonValid ? "valid" : "invalid"}`);
  return parts.join(" | ");
}

function metaString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function metaNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function metaBool(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

function shortID(id: string): string {
  return id.length > 8 ? id.slice(0, 8) : id;
}
