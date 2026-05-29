package realtime

// Wire protocol between the browser and the relay. The browser sends raw PCM
// audio as binary frames and control as JSON; the relay sends everything to
// the browser as JSON.

// ServerMessage is relay → browser. Only the fields relevant to Type are set.
type ServerMessage struct {
	Type string `json:"type"`

	// type=audio
	AudioPCM  string `json:"audio_pcm,omitempty"`
	AudioMIME string `json:"audio_mime,omitempty"`

	// type=transcript — speaker is "user" or "ai".
	Speaker string `json:"speaker,omitempty"`
	Text    string `json:"text,omitempty"`

	// type=error / type=status carry a code/text.
	Code string `json:"code,omitempty"`

	// type=ticket_created (intake mode): the queued extract job + its note.
	VoiceNoteID string `json:"voice_note_id,omitempty"`
	JobID       string `json:"job_id,omitempty"`
}

// Server message type constants.
const (
	ServerMsgReady         = "ready"
	ServerMsgAudio         = "audio"
	ServerMsgTranscript    = "transcript"
	ServerMsgTurnComplete  = "turn_complete"
	ServerMsgInterrupted   = "interrupted"
	ServerMsgStatus        = "status"
	ServerMsgError         = "error"
	ServerMsgTicketCreated = "ticket_created"
)

// ClientMessage is browser → relay (JSON control frames; audio is binary).
type ClientMessage struct {
	Type string `json:"type"`
}

// Client message type constants.
const (
	ClientMsgActivityStart = "activity_start"
	ClientMsgActivityEnd   = "activity_end"
	ClientMsgCreateTicket  = "create_ticket"
	ClientMsgEnd           = "end"
)
