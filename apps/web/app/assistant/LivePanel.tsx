"use client";

import Link from "next/link";
import type { AssistantMode, TranscriptLine } from "./types";

export function LivePanel({
  mode,
  enabled,
  live,
  status,
  searching,
  talking,
  transcript,
  ticketJobId,
  micLevel,
  aiLevel,
  error,
  onConnect,
  onToggleTalking,
  onDisconnect,
  onCreateTicket,
}: {
  mode: Exclude<AssistantMode, "upload">;
  enabled: boolean | null;
  live: boolean;
  status: string;
  searching: boolean;
  talking: boolean;
  transcript: TranscriptLine[];
  ticketJobId: string | null;
  micLevel: number;
  aiLevel: number;
  error: string;
  onConnect: () => void;
  onToggleTalking: () => void;
  onDisconnect: () => void;
  onCreateTicket: () => void;
}) {
  return (
    <div className="assistant-layout">
      <section className="card assistant-session">
        <div className="assistant-session-top">
          <div>
            <div className="muted" style={{ fontSize: 12 }}>
              {mode === "ticket" ? "Ticket intake" : "Knowledge base"}
            </div>
            <h2>{mode === "ticket" ? "Live ticket assistant" : "Live knowledge assistant"}</h2>
          </div>
          <span className="pill">{talking ? "listening" : searching ? "searching" : status}</span>
        </div>

        {enabled === false && (
          <p className="error">Live voice is unavailable. Use Upload note for recorded audio.</p>
        )}

        <div className="assistant-actions">
          {!live ? (
            <button className="primary" onClick={onConnect} disabled={enabled !== true || status === "connecting"}>
              {status === "connecting" ? "Connecting..." : "Start live session"}
            </button>
          ) : (
            <>
              <button
                type="button"
                className={`primary talk-button${talking ? " listening" : ""}`}
                aria-pressed={talking}
                onClick={onToggleTalking}
              >
                {talking ? "Listening - tap to stop" : "Tap to talk"}
              </button>
              {mode === "ticket" && <button onClick={onCreateTicket}>Create ticket</button>}
              <button onClick={onDisconnect}>End session</button>
            </>
          )}
        </div>

        {live && (
          <div className="grid two" style={{ marginTop: 16 }}>
            <Meter label="You" level={micLevel} />
            <Meter label="Assistant" level={aiLevel} />
          </div>
        )}

        {ticketJobId !== null && (
          <p className="muted" style={{ marginTop: 12 }}>
            Draft ticket queued. Track it in the{" "}
            <Link href="/review-queue" style={{ textDecoration: "underline" }}>
              review queue
            </Link>
            .
          </p>
        )}

        {error && <p className="error" style={{ marginTop: 12 }}>{error}</p>}
      </section>

      <section className="card transcript-panel">
        <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>Transcript</div>
        {transcript.length === 0 ? (
          <div className="empty-state">No transcript yet.</div>
        ) : (
          <div className="stack">
            {transcript.map((line, i) => (
              <div key={i}>
                <span className="muted" style={{ fontSize: 12 }}>
                  {line.speaker === "user" ? "You" : "Assistant"}
                </span>
                <div style={{ whiteSpace: "pre-wrap" }}>{line.text}</div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function Meter({ label, level }: { label: string; level: number }) {
  return (
    <div>
      <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>{label}</div>
      <div className="meter-track">
        <div className="meter-fill" style={{ width: `${Math.round(Math.min(1, level) * 100)}%` }} />
      </div>
    </div>
  );
}
