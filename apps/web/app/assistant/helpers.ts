// Pure helpers for the Assistant surface: WS URL building, transcript merging,
// and audio mime/format normalization for recorded-note upload.

import type { TranscriptLine } from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

// http -> ws, https -> wss. The handshake returns an absolute path.
export function toWsURL(path: string): string {
  return API_URL.replace(/^http/, "ws") + path;
}

// Append a transcript chunk, merging into the previous line when the same
// speaker is still talking so the log reads as sentences, not fragments.
export function mergeTranscript(
  lines: TranscriptLine[],
  speaker: "user" | "ai",
  text: string,
): TranscriptLine[] {
  const last = lines[lines.length - 1];
  if (last && last.speaker === speaker) {
    const next = lines.slice(0, -1);
    next.push({ speaker, text: last.text + text });
    return next;
  }
  return [...lines, { speaker, text }];
}

export function formatSize(bytes?: number): string {
  if (bytes == null) return "-";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remaining = seconds % 60;
  return `${minutes}:${remaining.toString().padStart(2, "0")}`;
}

export function normalizeAudioMime(value?: string): string {
  const base = (value ?? "").split(";")[0]?.trim().toLowerCase() ?? "";
  if (base === "audio/wave") return "audio/wav";
  if (base === "audio/x-m4a") return "audio/m4a";
  return base || "audio/mpeg";
}

function extensionForMime(mime: string): string {
  switch (mime) {
    case "audio/mp4":
    case "audio/m4a":
      return "m4a";
    case "audio/ogg":
      return "ogg";
    case "audio/wav":
    case "audio/x-wav":
      return "wav";
    case "audio/flac":
      return "flac";
    case "audio/webm":
      return "webm";
    default:
      return "mp3";
  }
}

export function pickRecorderMime(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/mp4",
    "audio/ogg;codecs=opus",
    "audio/ogg",
  ];
  return candidates.find((candidate) => MediaRecorder.isTypeSupported(candidate));
}

export function recordedFilename(mime: string): string {
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  return `voice-note-${stamp}.${extensionForMime(mime)}`;
}
