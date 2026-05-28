"use client";

import { useEffect, useState } from "react";
import { api } from "../../lib/api";

type VoiceNote = {
  id: string;
  object_key: string;
  mime_type: string;
  size_bytes?: number;
  status: string;
  created_at: string;
};

type CreateVoiceNoteResponse = VoiceNote;

type UploadURLResponse = {
  upload_url: string;
};

type UploadedResponse = {
  voice_note: VoiceNote;
  job: { id: string; type: string; status: string };
};

export default function VoiceNotesPage() {
  const [file, setFile] = useState<File | null>(null);
  const [items, setItems] = useState<VoiceNote[]>([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function load() {
    setError("");
    const res = await api<{ voice_notes: VoiceNote[] }>("/v1/voice-notes");
    setItems(res.voice_notes);
  }

  async function upload() {
    if (!file) {
      setError("Choose an audio file.");
      return;
    }
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const created = await api<CreateVoiceNoteResponse>("/v1/voice-notes", {
        method: "POST",
        body: JSON.stringify({
          filename: file.name,
          mime_type: file.type || "audio/mpeg",
          size_bytes: file.size,
        }),
      });
      const uploadURL = await api<UploadURLResponse>(`/v1/voice-notes/${created.id}/upload-url`, {
        method: "POST",
      });
      const put = await fetch(uploadURL.upload_url, {
        method: "PUT",
        headers: { "Content-Type": created.mime_type },
        body: file,
      });
      if (!put.ok) {
        throw new Error(`Upload failed: ${put.status} ${put.statusText}`);
      }
      const confirmed = await api<UploadedResponse>(`/v1/voice-notes/${created.id}/uploaded`, {
        method: "POST",
      });
      setMessage(`Queued ${confirmed.job.type} job ${confirmed.job.id}`);
      setFile(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h1 className="page-title">Voice Notes</h1>
      <div className="toolbar">
        <label className="field">
          <span>Audio file</span>
          <input
            type="file"
            accept="audio/*"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>
        <button className="primary" disabled={busy} onClick={upload}>
          Upload
        </button>
        <button disabled={busy} onClick={() => void load()}>
          Refresh
        </button>
      </div>
      {message && <p className="muted">{message}</p>}
      {error && <p className="error">{error}</p>}
      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>Created</th>
              <th>Status</th>
              <th>MIME</th>
              <th>Size</th>
              <th>ID</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id}>
                <td>{new Date(item.created_at).toLocaleString()}</td>
                <td><span className="pill">{item.status}</span></td>
                <td>{item.mime_type}</td>
                <td>{item.size_bytes ?? "—"}</td>
                <td>{item.id}</td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr>
                <td colSpan={5} className="muted">No voice notes.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
