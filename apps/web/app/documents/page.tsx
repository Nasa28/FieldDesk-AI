"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "../../lib/api";
import { formatTimestamp } from "../../lib/dashboard";

type Document = {
  id: string;
  title: string;
  source_type: string;
  mime_type?: string | null;
  size_bytes?: number | null;
  status: "pending" | "processing" | "ready" | "failed";
  parse_error?: string | null;
  chunk_count: number;
  created_at: string;
};

type ListResponse = { documents: Document[]; count: number };
type CreateResponse = Document & { mime_type: string };
type UploadURLResponse = { upload_url: string };
type UploadedResponse = {
  document: Document;
  job: { id: string; type: string; status: string };
};

// Allowed mime types map to filename extension hints so the browser file picker
// nudges users at upload time. Mirrors the Go handler's allowedDocumentMimes
// and the worker's parsing/base.SUPPORTED_MIME_TYPES.
const ACCEPT_HINT = ".txt,.md,.pdf,.docx,text/plain,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

const EXT_TO_MIME: Record<string, string> = {
  ".txt": "text/plain",
  ".md": "text/markdown",
  ".pdf": "application/pdf",
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
};

// Browsers report inconsistent mime types for some of these — Firefox calls
// markdown `text/x-markdown`, Safari leaves it blank. Normalize via extension
// before sending to the API so the supported-mime check on the server doesn't
// reject an upload over a browser quirk.
function effectiveMimeType(file: File): string {
  const lower = file.name.toLowerCase();
  for (const ext of Object.keys(EXT_TO_MIME)) {
    if (lower.endsWith(ext)) return EXT_TO_MIME[ext];
  }
  return file.type || "application/octet-stream";
}

function statusPillClass(status: Document["status"]): string {
  return status === "failed"
    ? "pill error"
    : status === "ready"
      ? "pill"
      : "pill"; // pending / processing share the neutral pill
}

export default function DocumentsPage() {
  const [items, setItems] = useState<Document[]>([]);
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const res = await api<ListResponse>("/v1/documents?limit=100");
      setItems(res.documents);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load documents.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function upload() {
    if (!file) {
      setError("Choose a document file.");
      return;
    }
    if (!title.trim()) {
      setError("Title is required.");
      return;
    }
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const mime = effectiveMimeType(file);
      const created = await api<CreateResponse>("/v1/documents", {
        method: "POST",
        body: JSON.stringify({
          title: title.trim(),
          filename: file.name,
          mime_type: mime,
          size_bytes: file.size,
        }),
      });
      const uploadURL = await api<UploadURLResponse>(
        `/v1/documents/${created.id}/upload-url`,
        { method: "POST" },
      );
      const put = await fetch(uploadURL.upload_url, {
        method: "PUT",
        headers: { "Content-Type": mime },
        body: file,
      });
      if (!put.ok) {
        throw new Error(`Upload failed: ${put.status} ${put.statusText}`);
      }
      const confirmed = await api<UploadedResponse>(
        `/v1/documents/${created.id}/uploaded`,
        { method: "POST" },
      );
      setMessage(`Queued ${confirmed.job.type} job ${confirmed.job.id}`);
      setFile(null);
      setTitle("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    if (!confirm("Delete this document? Chunks will be removed.")) return;
    setError("");
    try {
      await api(`/v1/documents/${id}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed.");
    }
  }

  return (
    <div>
      <h1 className="page-title">Documents</h1>
      <p className="page-subtitle">
        SOPs, manuals, warranty policies — anything you want surfaced when a
        new ticket comes in. Supported: <code>.txt</code>, <code>.md</code>,
        text-native <code>.pdf</code>, <code>.docx</code>.
      </p>

      <div className="card">
        <div className="toolbar">
          <label className="field" style={{ flex: 1, minWidth: 200 }}>
            <span>Title</span>
            <input
              placeholder="Hydraulic Pump 7000 — Troubleshooting"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
          <label className="field" style={{ flex: 2, minWidth: 280 }}>
            <span>File</span>
            <input
              type="file"
              accept={ACCEPT_HINT}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
          <button
            className="primary"
            disabled={busy || !file || !title.trim()}
            onClick={() => void upload()}
          >
            {busy ? "Uploading…" : "Upload"}
          </button>
          <button onClick={() => void load()} disabled={busy}>
            Refresh
          </button>
        </div>
        {message && <p className="muted">{message}</p>}
        {error && <p className="error">{error}</p>}
      </div>

      <div className="card" style={{ padding: 0 }}>
        <table className="table">
          <thead>
            <tr>
              <th>Title</th>
              <th>Type</th>
              <th>Size</th>
              <th>Chunks</th>
              <th>Status</th>
              <th>Uploaded</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && (
              <tr>
                <td colSpan={7} className="muted" style={{ padding: 16 }}>
                  No documents uploaded yet.
                </td>
              </tr>
            )}
            {items.map((d) => (
              <tr key={d.id}>
                <td>{d.title}</td>
                <td className="muted">{shortMime(d.mime_type)}</td>
                <td className="muted">{formatBytes(d.size_bytes)}</td>
                <td>{d.chunk_count}</td>
                <td>
                  <span className={statusPillClass(d.status)}>{d.status}</span>
                  {d.parse_error && (
                    <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                      {d.parse_error}
                    </div>
                  )}
                </td>
                <td className="muted">{formatTimestamp(d.created_at)}</td>
                <td>
                  <button onClick={() => void remove(d.id)}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function shortMime(mime?: string | null): string {
  if (!mime) return "—";
  if (mime.includes("wordprocessingml")) return "docx";
  if (mime === "application/pdf") return "pdf";
  if (mime.startsWith("text/markdown") || mime === "text/x-markdown") return "md";
  if (mime === "text/plain") return "txt";
  return mime;
}

function formatBytes(n?: number | null): string {
  if (!n || n <= 0) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
