"use client";

import type { RefObject } from "react";
import { formatDuration, formatSize } from "./helpers";
import type { VoiceNote } from "./types";

export function UploadPanel({
  file,
  audioPreviewURL,
  items,
  busy,
  recording,
  recordingSeconds,
  message,
  error,
  fileInputRef,
  onFile,
  onStartRecording,
  onStopRecording,
  onUpload,
  onRefresh,
}: {
  file: File | null;
  audioPreviewURL: string | null;
  items: VoiceNote[];
  busy: boolean;
  recording: boolean;
  recordingSeconds: number;
  message: string;
  error: string;
  fileInputRef: RefObject<HTMLInputElement | null>;
  onFile: (file: File | null) => void;
  onStartRecording: () => void;
  onStopRecording: () => void;
  onUpload: () => void;
  onRefresh: () => void;
}) {
  return (
    <div className="assistant-layout">
      <section className="card upload-panel">
        <div>
          <div className="muted" style={{ fontSize: 12 }}>Audio upload</div>
          <h2>Record or upload a note</h2>
        </div>
        <div className="recording-panel">
          <div>
            <div className="muted" style={{ fontSize: 12 }}>Recorder</div>
            <div className="recording-time">{recording ? formatDuration(recordingSeconds) : "Ready"}</div>
          </div>
          {recording ? (
            <button className="primary" disabled={busy} onClick={onStopRecording}>
              Stop recording
            </button>
          ) : (
            <button disabled={busy} onClick={onStartRecording}>
              Record audio
            </button>
          )}
        </div>
        <div className="file-picker">
          <input
            ref={fileInputRef}
            id="assistant-audio-file"
            className="sr-only"
            type="file"
            accept="audio/*"
            onChange={(e) => onFile(e.target.files?.[0] ?? null)}
          />
          <label htmlFor="assistant-audio-file" className="file-picker-button">
            Select audio
          </label>
          <div className="file-picker-name">
            {file ? `${file.name} (${formatSize(file.size)})` : "No file selected"}
          </div>
        </div>
        {audioPreviewURL && (
          <audio className="audio-preview" controls src={audioPreviewURL} aria-label="Selected audio preview" />
        )}
        <div className="toolbar" style={{ marginBottom: 0 }}>
          <button className="primary" disabled={busy || recording} onClick={onUpload}>Upload note</button>
          <button disabled={busy || recording} onClick={onRefresh}>Refresh</button>
        </div>
        {message && <p className="muted">{message}</p>}
        {error && <p className="error">{error}</p>}
      </section>

      <section className="card history-panel">
        <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>Recent uploads</div>
        {items.length === 0 ? (
          <div className="empty-state">No uploaded notes yet.</div>
        ) : (
          <table className="table compact">
            <thead>
              <tr>
                <th>Created</th>
                <th>Status</th>
                <th>File</th>
                <th>Size</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td>{new Date(item.created_at).toLocaleString()}</td>
                  <td><span className="pill">{item.status}</span></td>
                  <td>{item.mime_type}</td>
                  <td>{formatSize(item.size_bytes)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
