"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../lib/api";
import { PCMPlayer, PCMRecorder } from "../voice/audio";
import { LivePanel } from "./LivePanel";
import { UploadPanel } from "./UploadPanel";
import {
  mergeTranscript,
  normalizeAudioMime,
  pickRecorderMime,
  recordedFilename,
  toWsURL,
} from "./helpers";
import type {
  AssistantMode,
  CreateVoiceNoteResponse,
  LiveMode,
  ServerMessage,
  SessionResponse,
  TranscriptLine,
  UploadURLResponse,
  UploadedResponse,
  VoiceConfig,
  VoiceNote,
} from "./types";

export default function AssistantPage() {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [mode, setMode] = useState<AssistantMode>("ticket");
  const [status, setStatus] = useState<"idle" | "connecting" | "live" | "error" | "ended">("idle");
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState("");
  const [talking, setTalking] = useState(false);
  const [transcript, setTranscript] = useState<TranscriptLine[]>([]);
  const [ticketJobId, setTicketJobId] = useState<string | null>(null);
  const [aiLevel, setAiLevel] = useState(0);
  const [micLevel, setMicLevel] = useState(0);

  const [file, setFile] = useState<File | null>(null);
  const [voiceNotes, setVoiceNotes] = useState<VoiceNote[]>([]);
  const [uploadMessage, setUploadMessage] = useState("");
  const [uploadError, setUploadError] = useState("");
  const [uploadBusy, setUploadBusy] = useState(false);
  const [recording, setRecording] = useState(false);
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const [recordingStartedAt, setRecordingStartedAt] = useState<number | null>(null);
  const [audioPreviewURL, setAudioPreviewURL] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const recorderRef = useRef<PCMRecorder | null>(null);
  const playerRef = useRef<PCMPlayer | null>(null);
  const talkingRef = useRef(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const uploadRecorderRef = useRef<MediaRecorder | null>(null);
  const uploadRecordingStreamRef = useRef<MediaStream | null>(null);
  const uploadRecordingChunksRef = useRef<Blob[]>([]);

  const live = status === "live";
  const connected = status === "connecting" || live;
  const liveMode: LiveMode = mode === "ticket" ? "intake" : "qa";

  const loadVoiceNotes = useCallback(async () => {
    const res = await api<{ voice_notes: VoiceNote[] }>("/v1/voice-notes");
    setVoiceNotes(res.voice_notes);
  }, []);

  useEffect(() => {
    let cancelled = false;
    api<VoiceConfig>("/v1/voice/config")
      .then((c) => {
        if (!cancelled) setEnabled(c.voice_enabled);
      })
      .catch(() => {
        if (!cancelled) setEnabled(false);
      });
    void loadVoiceNotes().catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [loadVoiceNotes]);

  useEffect(() => {
    if (!file) {
      setAudioPreviewURL(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setAudioPreviewURL(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  useEffect(() => {
    if (!recording || recordingStartedAt == null) return;
    const timer = window.setInterval(() => {
      setRecordingSeconds(Math.floor((Date.now() - recordingStartedAt) / 1000));
    }, 250);
    return () => window.clearInterval(timer);
  }, [recording, recordingStartedAt]);

  const teardown = useCallback(() => {
    recorderRef.current?.stop();
    recorderRef.current = null;
    playerRef.current?.dispose();
    playerRef.current = null;
    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.close();
      wsRef.current = null;
    }
    talkingRef.current = false;
    setTalking(false);
    setAiLevel(0);
    setMicLevel(0);
    setSearching(false);
  }, []);

  useEffect(() => () => teardown(), [teardown]);

  const connect = useCallback(async () => {
    if (enabled !== true || mode === "upload") return;
    setError("");
    setStatus("connecting");
    setTranscript([]);
    setTicketJobId(null);
    try {
      const session = await api<SessionResponse>(`/v1/voice/sessions?mode=${liveMode}`, { method: "POST" });
      const player = new PCMPlayer(setAiLevel);
      const recorder = new PCMRecorder({
        onChunk: (chunk) => {
          const ws = wsRef.current;
          if (talkingRef.current && ws && ws.readyState === WebSocket.OPEN) ws.send(chunk);
        },
        onLevel: setMicLevel,
      });
      await recorder.start();
      playerRef.current = player;
      recorderRef.current = recorder;

      const ws = new WebSocket(toWsURL(session.ws_url));
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;

      ws.onmessage = (event) => {
        if (typeof event.data !== "string") return;
        const msg = JSON.parse(event.data) as ServerMessage;
        switch (msg.type) {
          case "ready":
            setStatus("live");
            break;
          case "audio":
            setSearching(false);
            if (msg.audio_pcm) void player.playBase64PCM(msg.audio_pcm, msg.audio_mime ?? "audio/pcm;rate=24000");
            break;
          case "transcript":
            if (msg.text && msg.speaker) {
              setTranscript((lines) => mergeTranscript(lines, msg.speaker!, msg.text!));
            }
            break;
          case "turn_complete":
            setSearching(false);
            break;
          case "interrupted":
            player.interrupt();
            break;
          case "status":
            setSearching(msg.code === "searching");
            if (msg.code === "searching" || msg.code === "grounded") setError("");
            if (msg.code === "search_required") {
              setError("The assistant tried to answer before checking the knowledge base. Ask again.");
            }
            break;
          case "ticket_created":
            setTicketJobId(msg.job_id ?? "");
            break;
          case "error":
            if (msg.code === "ticket_failed") {
              setError("Could not create the ticket from this conversation.");
              break;
            }
            setError(msg.code === "provider_unavailable" ? "Voice service is unavailable." : "The voice stream ended.");
            teardown();
            setStatus("error");
            break;
        }
      };
      ws.onclose = () => {
        if (wsRef.current === ws) {
          teardown();
          setStatus("ended");
        }
      };
      ws.onerror = () => setError("Connection error.");
    } catch (err) {
      teardown();
      setStatus("error");
      setError(err instanceof Error ? err.message : "Could not start the voice session.");
    }
  }, [enabled, liveMode, mode, teardown]);

  const sendControl = useCallback((type: string) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type }));
  }, []);

  const startTalking = useCallback(() => {
    if (status !== "live" || talkingRef.current) return;
    talkingRef.current = true;
    setTalking(true);
    sendControl("activity_start");
  }, [status, sendControl]);

  const stopTalking = useCallback(() => {
    if (!talkingRef.current) return;
    sendControl("activity_end");
    talkingRef.current = false;
    setTalking(false);
  }, [sendControl]);

  const toggleTalking = useCallback(() => {
    if (talkingRef.current) {
      stopTalking();
      return;
    }
    startTalking();
  }, [startTalking, stopTalking]);

  const disconnect = useCallback(() => {
    stopTalking();
    sendControl("end");
    teardown();
    setStatus("idle");
  }, [sendControl, stopTalking, teardown]);

  const createTicketFromConversation = useCallback(() => {
    stopTalking();
    sendControl("create_ticket");
  }, [sendControl, stopTalking]);

  const stopUploadRecordingStream = useCallback(() => {
    uploadRecordingStreamRef.current?.getTracks().forEach((track) => track.stop());
    uploadRecordingStreamRef.current = null;
  }, []);

  useEffect(() => {
    return () => {
      const recorder = uploadRecorderRef.current;
      if (recorder) {
        recorder.ondataavailable = null;
        recorder.onstop = null;
        recorder.onerror = null;
        if (recorder.state !== "inactive") recorder.stop();
      }
      uploadRecorderRef.current = null;
      stopUploadRecordingStream();
    };
  }, [stopUploadRecordingStream]);

  const startRecordingNote = useCallback(async () => {
    if (uploadBusy || recording) return;
    if (typeof MediaRecorder === "undefined") {
      setUploadError("Audio recording is not supported in this browser.");
      return;
    }
    setUploadError("");
    setUploadMessage("");
    setRecordingSeconds(0);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      const mimeType = pickRecorderMime();
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      uploadRecordingStreamRef.current = stream;
      uploadRecordingChunksRef.current = [];
      uploadRecorderRef.current = recorder;

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) uploadRecordingChunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        const chunks = uploadRecordingChunksRef.current;
        uploadRecordingChunksRef.current = [];
        uploadRecorderRef.current = null;
        stopUploadRecordingStream();
        setRecording(false);
        setRecordingStartedAt(null);
        if (chunks.length === 0) {
          setUploadError("No audio was captured.");
          return;
        }
        const mime = normalizeAudioMime(recorder.mimeType || chunks[0]?.type || mimeType);
        const blob = new Blob(chunks, { type: mime });
        const nextFile = new File([blob], recordedFilename(mime), { type: mime });
        setFile(nextFile);
        if (fileInputRef.current) fileInputRef.current.value = "";
        setUploadMessage("Recording ready to upload.");
      };
      recorder.onerror = () => {
        uploadRecorderRef.current = null;
        stopUploadRecordingStream();
        setRecording(false);
        setRecordingStartedAt(null);
        setUploadError("Recording failed.");
      };
      recorder.start();
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      setRecordingStartedAt(Date.now());
      setRecording(true);
    } catch (err) {
      stopUploadRecordingStream();
      setRecording(false);
      setRecordingStartedAt(null);
      setUploadError(err instanceof Error ? err.message : "Could not start recording.");
    }
  }, [recording, stopUploadRecordingStream, uploadBusy]);

  const stopRecordingNote = useCallback(() => {
    const recorder = uploadRecorderRef.current;
    if (!recorder || recorder.state === "inactive") return;
    recorder.stop();
  }, []);

  async function upload() {
    if (!file) {
      setUploadError("Choose or record an audio file.");
      return;
    }
    setUploadBusy(true);
    setUploadError("");
    setUploadMessage("");
    try {
      const mime = normalizeAudioMime(file.type);
      const created = await api<CreateVoiceNoteResponse>("/v1/voice-notes", {
        method: "POST",
        body: JSON.stringify({ filename: file.name, mime_type: mime, size_bytes: file.size }),
      });
      const uploadURL = await api<UploadURLResponse>(`/v1/voice-notes/${created.id}/upload-url`, {
        method: "POST",
      });
      const put = await fetch(uploadURL.upload_url, {
        method: "PUT",
        headers: { "Content-Type": created.mime_type },
        body: file,
      });
      if (!put.ok) throw new Error(`Upload failed: ${put.status} ${put.statusText}`);
      const confirmed = await api<UploadedResponse>(`/v1/voice-notes/${created.id}/uploaded`, {
        method: "POST",
      });
      setUploadMessage(`Queued ${confirmed.job.type} job ${confirmed.job.id}`);
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      await loadVoiceNotes();
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setUploadBusy(false);
    }
  }

  function selectMode(next: AssistantMode) {
    if (connected) return;
    setMode(next);
    setError("");
    setUploadError("");
    setUploadMessage("");
  }

  return (
    <div>
      <div className="assistant-header">
        <div>
          <h1 className="page-title">Assistant</h1>
          <p className="page-subtitle">Create tickets, ask the knowledge base, or upload a recorded note.</p>
        </div>
        <span className="pill">{connected ? status : enabled === false ? "voice off" : "ready"}</span>
      </div>

      <div className="segmented" role="tablist" aria-label="Assistant mode">
        {(["ticket", "knowledge", "upload"] as const).map((value) => (
          <button
            key={value}
            role="tab"
            aria-selected={mode === value}
            className={mode === value ? "active" : ""}
            disabled={connected}
            onClick={() => selectMode(value)}
          >
            {value === "ticket" ? "Create ticket" : value === "knowledge" ? "Ask knowledge base" : "Upload note"}
          </button>
        ))}
      </div>

      {mode !== "upload" ? (
        <LivePanel
          mode={mode}
          enabled={enabled}
          live={live}
          status={status}
          searching={searching}
          talking={talking}
          transcript={transcript}
          ticketJobId={ticketJobId}
          micLevel={micLevel}
          aiLevel={aiLevel}
          error={error}
          onConnect={() => void connect()}
          onToggleTalking={toggleTalking}
          onDisconnect={disconnect}
          onCreateTicket={createTicketFromConversation}
        />
      ) : (
        <UploadPanel
          file={file}
          audioPreviewURL={audioPreviewURL}
          items={voiceNotes}
          busy={uploadBusy}
          recording={recording}
          recordingSeconds={recordingSeconds}
          message={uploadMessage}
          error={uploadError}
          fileInputRef={fileInputRef}
          onFile={(nextFile) => {
            setFile(nextFile);
            setUploadError("");
            setUploadMessage("");
          }}
          onStartRecording={() => void startRecordingNote()}
          onStopRecording={stopRecordingNote}
          onUpload={() => void upload()}
          onRefresh={() => void loadVoiceNotes()}
        />
      )}
    </div>
  );
}
