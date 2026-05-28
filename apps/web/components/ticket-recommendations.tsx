"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { formatTimestamp, formatUSD } from "../lib/dashboard";

/**
 * Contract — Phase 4.5 / Sub-slice B.
 *
 * GET /v1/tickets/{id}/recommendations returns the denormalized view defined
 * in apps/api/internal/database/recommendations.go (TicketRecommendation).
 *
 * Citations are enriched server-side: the API joins citation chunk_ids
 * against the rag_query that drove the synthesis and attaches document
 * metadata. Hallucinated chunk_ids (ones the model emitted that weren't in
 * the retrieval set) are dropped on the server, so the client never has to
 * decide whether to render unattributable citations.
 *
 * 404 from the API means the draft_ticket synthesis job is still in flight —
 * surfaced as a pending state, not an error (same pattern as RelatedDocuments).
 */
type EnrichedCitation = {
  chunk_id: string;
  note?: string | null;
  document_id?: string | null;
  document_title?: string | null;
  heading_path?: string[] | null;
  source_page?: number | null;
};

type TicketRecommendation = {
  id: string;
  tenant_id: string;
  job_ticket_id: string;
  rag_query_id?: string | null;

  possible_diagnosis: string | null;
  suggested_parts: string[];
  safety_checklist: string[];
  follow_up_questions: string[];
  citations: EnrichedCitation[];
  insufficient_context: boolean;
  notes: string | null;
  confidence: number;
  json_valid: boolean;

  provider: string;
  model: string;
  prompt_version: string;
  schema_version: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  duration_ms: number;
  error_message?: string | null;
  created_at: string;
};

function isPendingError(msg: string): boolean {
  const lower = msg.toLowerCase();
  return (
    lower.includes("no recommendations yet") ||
    lower.includes("not found") ||
    msg.includes("404")
  );
}

function confidenceBucket(confidence: number): {
  label: string;
  color: string;
} {
  if (confidence >= 0.75) return { label: "high", color: "#3aa66c" };
  if (confidence >= 0.5) return { label: "medium", color: "#c2a23a" };
  return { label: "low", color: "#c25a3a" };
}

/**
 * Renders auto-synthesized ticket recommendations (suggested parts, safety
 * checklist, follow-up questions, possible diagnosis) plus enriched chunk
 * citations.
 *
 * Surfaces three states the worker writes deliberately, so an operator can
 * see *why* a card looks empty:
 *   1. json_valid=false + error_message — the LLM returned bad JSON; the row
 *      was persisted in a degraded form. Show the error so the operator
 *      doesn't mistake this for "no docs uploaded yet."
 *   2. insufficient_context=true + notes — zero chunks retrieved, or the
 *      model self-judged the chunks too thin. notes carries the worker's
 *      reason ("Retrieval returned zero matching chunks" / etc).
 *   3. 404 — the draft_ticket synthesis job hasn't completed yet (same
 *      pending pattern as RelatedDocuments).
 *
 * Security-relevant: every string rendered here originated in tenant-
 * uploaded documents and went through the LLM. Plain text only — no
 * dangerouslySetInnerHTML, no href construction from chunk content. A
 * hostile document can mislead the operator at worst, never execute
 * anything in the browser.
 */
export function TicketRecommendations({ ticketId }: { ticketId: string }) {
  const [recs, setRecs] = useState<TicketRecommendation | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    setPending(false);
    try {
      const res = await api<TicketRecommendation>(
        `/v1/tickets/${ticketId}/recommendations`,
      );
      setRecs(res);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (isPendingError(msg)) {
        setRecs(null);
        setPending(true);
      } else {
        setRecs(null);
        setError(msg);
      }
    } finally {
      setLoading(false);
    }
  }, [ticketId]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div
      style={{
        marginTop: 16,
        borderTop: "1px solid var(--border)",
        paddingTop: 12,
      }}
    >
      <div className="toolbar" style={{ marginBottom: 8 }}>
        <div style={{ flex: 1 }}>
          <div className="muted" style={{ fontSize: 12 }}>
            Suggestions
          </div>
          {recs && <RecsMetaLine recs={recs} />}
        </div>
        <button onClick={() => void load()} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      {pending && !error && (
        <p className="muted" style={{ fontSize: 12 }}>
          No suggestions yet — the draft_ticket job is still queued. Click Refresh in a moment.
        </p>
      )}

      {recs && <RecsBody recs={recs} />}
    </div>
  );
}

function RecsMetaLine({ recs }: { recs: TicketRecommendation }) {
  const bucket = confidenceBucket(recs.confidence);
  return (
    <div className="muted" style={{ fontSize: 11 }}>
      Synthesized {formatTimestamp(recs.created_at)} · {recs.duration_ms} ms
      · {formatUSD(recs.cost_usd)} · {recs.model}
      <span style={{ marginLeft: 8, color: bucket.color }}>
        confidence {recs.confidence.toFixed(2)} ({bucket.label})
      </span>
    </div>
  );
}

function RecsBody({ recs }: { recs: TicketRecommendation }) {
  // json_valid=false is a real failure path the worker preserves rather than
  // silently dropping. Show it prominently above everything else so an
  // operator doesn't confuse a degraded synthesis with an empty one.
  if (!recs.json_valid) {
    return (
      <div className="error" style={{ fontSize: 13 }}>
        Synthesis returned invalid JSON; recommendations were not produced.
        {recs.error_message && (
          <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
            {recs.error_message}
          </div>
        )}
      </div>
    );
  }

  if (recs.insufficient_context) {
    return (
      <p className="muted" style={{ fontSize: 12 }}>
        {recs.notes ?? "Insufficient context — no recommendations generated."}
      </p>
    );
  }

  const hasAny =
    recs.suggested_parts.length > 0 ||
    recs.safety_checklist.length > 0 ||
    recs.follow_up_questions.length > 0 ||
    !!recs.possible_diagnosis;

  if (!hasAny) {
    return (
      <p className="muted" style={{ fontSize: 12 }}>
        Synthesis completed but produced no recommendations.
        {recs.notes && <span style={{ marginLeft: 4 }}>{recs.notes}</span>}
      </p>
    );
  }

  return (
    <div style={{ display: "grid", gap: 12 }}>
      {recs.possible_diagnosis && (
        <RecSection label="Possible diagnosis">
          <p style={{ margin: 0 }}>{recs.possible_diagnosis}</p>
        </RecSection>
      )}
      {recs.suggested_parts.length > 0 && (
        <RecSection label="Suggested parts">
          <BulletList items={recs.suggested_parts} />
        </RecSection>
      )}
      {recs.safety_checklist.length > 0 && (
        <RecSection label="Safety checklist" accent="warn">
          <BulletList items={recs.safety_checklist} />
        </RecSection>
      )}
      {recs.follow_up_questions.length > 0 && (
        <RecSection label="Follow-up questions">
          <BulletList items={recs.follow_up_questions} />
        </RecSection>
      )}
      {recs.citations.length > 0 && (
        <RecSection label="Citations">
          <CitationList citations={recs.citations} />
        </RecSection>
      )}
      {recs.notes && (
        <p className="muted" style={{ fontSize: 11, margin: 0 }}>
          {recs.notes}
        </p>
      )}
    </div>
  );
}

function CitationList({ citations }: { citations: EnrichedCitation[] }) {
  return (
    <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12 }}>
      {citations.map((c) => (
        <li key={c.chunk_id} className="muted">
          {c.document_title ?? c.chunk_id}
          {c.heading_path && c.heading_path.length > 0 && (
            <> · {c.heading_path.join(" › ")}</>
          )}
          {c.source_page != null && <> · p. {c.source_page}</>}
          {c.note && (
            <span style={{ marginLeft: 4, fontStyle: "italic" }}>
              — {c.note}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

function RecSection({
  label,
  accent,
  children,
}: {
  label: string;
  accent?: "warn";
  children: React.ReactNode;
}) {
  return (
    <div>
      <div
        className="muted"
        style={{
          fontSize: 11,
          fontWeight: 600,
          textTransform: "uppercase",
          letterSpacing: 0,
          color: accent === "warn" ? "#f0b400" : undefined,
          marginBottom: 4,
        }}
      >
        {label}
      </div>
      {children}
    </div>
  );
}

function BulletList({ items }: { items: string[] }) {
  return (
    <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13 }}>
      {items.map((item, i) => (
        <li key={`${i}:${item}`}>{item}</li>
      ))}
    </ul>
  );
}
