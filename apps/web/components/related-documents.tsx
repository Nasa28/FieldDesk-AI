"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { formatTimestamp } from "../lib/dashboard";

type RetrievedChunk = {
  chunk_id: string;
  document_id: string;
  document_title: string;
  text: string;
  heading_path: string[];
  source_page?: number | null;
  source_locator?: Record<string, unknown>;
  dense_rank?: number | null;
  lexical_rank?: number | null;
  fused_score: number;
};

type RAGQuery = {
  id: string;
  query_text: string;
  top_k: number;
  results: RetrievedChunk[] | string; // server returns RawMessage, may be string or array
  embedding_model?: string | null;
  cost_usd: number;
  duration_ms: number;
  created_at: string;
};

function parseResults(raw: RAGQuery["results"]): RetrievedChunk[] {
  if (Array.isArray(raw)) return raw;
  if (typeof raw === "string") {
    try {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? (parsed as RetrievedChunk[]) : [];
    } catch {
      return [];
    }
  }
  return [];
}

function truncate(s: string, n: number): string {
  if (s.length <= n) return s;
  return s.slice(0, n).trimEnd() + "…";
}

/**
 * Reads the latest rag_queries row for a ticket and renders the retrieved
 * chunks with citations. Returns a "not yet" state when the rag job is
 * still in flight (404 from the API), letting the caller's Refresh button
 * be the polling mechanism rather than implementing a setInterval that
 * leaks across navigation.
 */
export function RelatedDocuments({ ticketId }: { ticketId: string }) {
  const [query, setQuery] = useState<RAGQuery | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    setPending(false);
    try {
      const res = await api<RAGQuery>(`/v1/rag/queries/by-ticket/${ticketId}`);
      setQuery(res);
    } catch (err) {
      // The API returns 404 when no rag_queries row exists yet — that means
      // the auto-enqueued rag job hasn't finished, not that anything's
      // broken. Surface as "Pending" rather than a red error.
      const msg = err instanceof Error ? err.message : String(err);
      const lower = msg.toLowerCase();
      if (
        lower.includes("no rag query yet")
        || lower.includes("not found")
        || msg.includes("404")
      ) {
        setQuery(null);
        setPending(true);
      } else {
        setQuery(null);
        setError(msg);
      }
    } finally {
      setLoading(false);
    }
  }, [ticketId]);

  useEffect(() => {
    void load();
  }, [load]);

  const results = query ? parseResults(query.results) : [];

  return (
    <div style={{ marginTop: 16, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
      <div className="toolbar" style={{ marginBottom: 8 }}>
        <div style={{ flex: 1 }}>
          <div className="muted" style={{ fontSize: 12 }}>Related documents</div>
          {query && (
            <div className="muted" style={{ fontSize: 11 }}>
              Retrieved {formatTimestamp(query.created_at)} • {query.duration_ms} ms •
              ${query.cost_usd.toFixed(6)}
            </div>
          )}
        </div>
        <button onClick={() => void load()} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      {pending && !error && (
        <p className="muted" style={{ fontSize: 12 }}>
          No retrieval yet — the rag job is still queued. Click Refresh in a moment.
        </p>
      )}

      {!pending && !error && results.length === 0 && query && (
        <p className="muted" style={{ fontSize: 12 }}>
          No matching chunks. Upload SOPs or manuals on the Documents page.
        </p>
      )}

      {results.map((r) => (
        <div
          key={r.chunk_id}
          className="muted"
          style={{
            fontSize: 12,
            padding: "8px 0",
            borderTop: "1px dashed var(--border)",
          }}
        >
          <div style={{ color: "var(--text)" }}>
            <strong>{r.document_title}</strong>
            {r.heading_path.length > 0 && (
              <span className="muted"> · {r.heading_path.join(" › ")}</span>
            )}
            {r.source_page != null && (
              <span className="muted"> · p. {r.source_page}</span>
            )}
          </div>
          <div style={{ marginTop: 4 }}>{truncate(r.text, 320)}</div>
          <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
            score {r.fused_score.toFixed(4)}
            {r.dense_rank != null && <> · dense #{r.dense_rank}</>}
            {r.lexical_rank != null && <> · lexical #{r.lexical_rank}</>}
          </div>
        </div>
      ))}
    </div>
  );
}
