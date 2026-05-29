// Shared types for the Assistant surface (live voice + recorded-note upload).

export type VoiceConfig = { voice_enabled: boolean };
export type SessionResponse = { ws_url: string };

export type ServerMessage = {
  type: string;
  audio_pcm?: string;
  audio_mime?: string;
  speaker?: "user" | "ai";
  text?: string;
  code?: string;
  voice_note_id?: string;
  job_id?: string;
};

export type VoiceNote = {
  id: string;
  object_key: string;
  mime_type: string;
  size_bytes?: number;
  status: string;
  created_at: string;
};

export type CreateVoiceNoteResponse = VoiceNote;
export type UploadURLResponse = { upload_url: string };
export type UploadedResponse = {
  voice_note: VoiceNote;
  job: { id: string; type: string; status: string };
};

export type AssistantMode = "ticket" | "knowledge" | "upload";
export type LiveMode = "qa" | "intake";
export type TranscriptLine = { speaker: "user" | "ai"; text: string };
