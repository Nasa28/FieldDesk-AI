"use client";

import { useState } from "react";
import { api } from "../../lib/api";
import { formatUSD } from "../../lib/dashboard";

type SearchResponse = {
  job_id: string;
  status: string;
  job_url: string;
  query: {
    text: string;
    top_k: number;
    answer?: boolean;
  };
};

type RetrievedChunk = {
  chunk_id: string;
  document_id: string;
  document_title: string;
  text: string;
  heading_path?: string[];
  source_page?: number | null;
  dense_rank?: number | null;
  lexical_rank?: number | null;
  fused_score?: number;
  rerank_score?: number;
};

type KnowledgeAnswer = {
  answer: string | null;
  citations: { chunk_id: string; note?: string | null }[];
  follow_up_questions: string[];
  confidence: number;
  insufficient_context: boolean;
  notes: string | null;
  provider: string;
  model: string;
  cost_usd: number;
  duration_ms: number;
  json_valid: boolean;
  grounding_valid: boolean;
  error_message?: string | null;
};

type RAGJobResult = {
  rag_query_id: string;
  chunks: number;
  results: RetrievedChunk[];
  answer?: KnowledgeAnswer;
  cost_usd: number;
  answer_cost_usd?: number;
  duration_ms: number;
  embedding_model: string;
};

type AIJobResponse = {
  job: {
    id: string;
    type: string;
    status: string;
    result?: RAGJobResult | string | null;
    error_class?: string | null;
    error_message?: string | null;
  };
};

const DEFAULT_QUESTION = "";

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function parseResult(raw: AIJobResponse["job"]["result"]): RAGJobResult | null {
  if (!raw) return null;
  if (typeof raw === "object") return raw as RAGJobResult;
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? (parsed as RAGJobResult) : null;
  } catch {
    return null;
  }
}

function truncate(text: string, max = 520): string {
  if (text.length <= max) return text;
  return text.slice(0, max).trimEnd() + "...";
}

export default function KnowledgePage() {
  const [question, setQuestion] = useState(DEFAULT_QUESTION);
  const [topK, setTopK] = useState(5);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [result, setResult] = useState<RAGJobResult | null>(null);

  async function ask() {
    const query = question.trim();
    if (!query) {
      setError("Enter a question.");
      return;
    }
    setBusy(true);
    setError("");
    setResult(null);
    setStatus("Queued");
    try {
      const queued = await api<SearchResponse>("/v1/rag/ask", {
        method: "POST",
        body: JSON.stringify({ query_text: query, top_k: topK }),
      });
      await pollJob(queued.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not ask knowledge base.");
    } finally {
      setBusy(false);
    }
  }

  async function pollJob(jobId: string) {
    for (let i = 0; i < 50; i += 1) {
      const res = await api<AIJobResponse>(`/v1/ai-jobs/${jobId}`);
      const job = res.job;
      setStatus(job.status);
      if (job.status === "succeeded") {
        setResult(parseResult(job.result));
        return;
      }
      if (job.status === "failed" || job.status === "needs_review") {
        throw new Error(job.error_message ?? `RAG job ${job.status}`);
      }
      await sleep(1500);
    }
    throw new Error("Timed out waiting for the knowledge-base answer.");
  }

  return (
    <div>
      <h1 className="page-title">Knowledge Base</h1>

      <div className="card">
        <label className="field">
          <span>Question</span>
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="What should I check before entering a confined space?"
          />
        </label>
        <div className="toolbar" style={{ marginTop: 12 }}>
          <label className="field" style={{ width: 140, minWidth: 140 }}>
            <span>Sources</span>
            <select
              value={topK}
              onChange={(e) => setTopK(Number(e.target.value))}
            >
              <option value={3}>Top 3</option>
              <option value={5}>Top 5</option>
              <option value={8}>Top 8</option>
            </select>
          </label>
          <button className="primary" onClick={() => void ask()} disabled={busy}>
            {busy ? "Working..." : "Ask"}
          </button>
          {status && <span className="pill">{status}</span>}
        </div>
        {error && <p className="error">{error}</p>}
      </div>

      {result && <AnswerResult result={result} />}
    </div>
  );
}

function AnswerResult({ result }: { result: RAGJobResult }) {
  const answer = result.answer;
  const totalCost = result.cost_usd + (result.answer_cost_usd ?? 0);
  return (
    <div className="stack">
      <div className="card">
        <div className="toolbar">
          <div style={{ flex: 1 }}>
            <div className="muted" style={{ fontSize: 12 }}>
              Answer
            </div>
            <div className="muted" style={{ fontSize: 11 }}>
              {result.duration_ms} ms retrieval - {formatUSD(totalCost)}
              {answer?.model ? ` - ${answer.model}` : ""}
            </div>
          </div>
          {answer && (
            <span className="pill">confidence {answer.confidence.toFixed(2)}</span>
          )}
        </div>

        {!answer && (
          <p className="muted">Retrieved passages are available below.</p>
        )}

        {answer && !answer.json_valid && (
          <p className="error">
            The answer was not valid JSON.
            {answer.error_message ? ` ${answer.error_message}` : ""}
          </p>
        )}

        {answer?.insufficient_context && (
          <p className="muted">
            {answer.notes ?? "The retrieved documents did not contain enough context."}
          </p>
        )}

        {answer?.answer && (
          <p style={{ marginBottom: 0, whiteSpace: "pre-wrap" }}>{answer.answer}</p>
        )}

        {answer && answer.citations.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
              Citations
            </div>
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {answer.citations.map((citation) => {
                const source = result.results.find(
                  (chunk) => chunk.chunk_id === citation.chunk_id,
                );
                return (
                  <li key={citation.chunk_id} className="muted">
                    {source?.document_title ?? citation.chunk_id}
                    {source?.source_page != null && <> - p. {source.source_page}</>}
                    {citation.note && <> - {citation.note}</>}
                  </li>
                );
              })}
            </ul>
          </div>
        )}

        {answer && answer.follow_up_questions.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
              Follow-up
            </div>
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {answer.follow_up_questions.map((q) => (
                <li key={q}>{q}</li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div className="card" style={{ padding: 0 }}>
        <table className="table">
          <thead>
            <tr>
              <th>Source</th>
              <th>Passage</th>
              <th>Rank</th>
            </tr>
          </thead>
          <tbody>
            {result.results.length === 0 && (
              <tr>
                <td colSpan={3} className="muted" style={{ padding: 16 }}>
                  No matching document chunks.
                </td>
              </tr>
            )}
            {result.results.map((chunk) => (
              <tr key={chunk.chunk_id}>
                <td>
                  <strong>{chunk.document_title}</strong>
                  {chunk.heading_path && chunk.heading_path.length > 0 && (
                    <div className="muted" style={{ fontSize: 12 }}>
                      {chunk.heading_path.join(" / ")}
                    </div>
                  )}
                  {chunk.source_page != null && (
                    <div className="muted" style={{ fontSize: 12 }}>
                      p. {chunk.source_page}
                    </div>
                  )}
                </td>
                <td className="muted">{truncate(chunk.text)}</td>
                <td className="muted" style={{ whiteSpace: "nowrap" }}>
                  {chunk.rerank_score != null
                    ? chunk.rerank_score.toFixed(3)
                    : chunk.fused_score?.toFixed(4) ?? "-"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
