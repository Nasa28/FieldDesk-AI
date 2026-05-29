package voicelive

import "context"

// SearchToolName is the function-declaration name the model calls to ground
// its answer in the tenant's knowledge base. The relay handles the call by
// running retrieval and sending back a tool response.
const SearchToolName = "search_knowledge_base"

// EventType enumerates the normalized events a session surfaces on its
// Events() channel. We deliberately collapse Gemini's wire shapes into a
// small set the relay can translate to browser messages without knowing the
// Gemini protocol.
type EventType int

const (
	EventSetupComplete EventType = iota
	EventAudioChunk
	EventInputTranscript
	EventOutputTranscript
	EventTurnComplete
	EventInterrupted
	EventToolCall
	EventError
)

// Event is one normalized message from the upstream model session. Only the
// fields relevant to Type are populated.
type Event struct {
	Type EventType

	// EventAudioChunk: base64-encoded PCM and its mime (e.g. audio/pcm;rate=24000).
	AudioPCM  string
	AudioMIME string

	// EventInputTranscript / EventOutputTranscript.
	TranscriptText string

	// EventToolCall: the function call the model wants the relay to fulfil.
	ToolCallID string
	ToolName   string
	ToolArgs   map[string]any

	// EventError.
	Err error
}

// SessionConfig is the per-connection setup passed to Provider.Connect.
type SessionConfig struct {
	SystemPrompt string
	VoiceName    string
	// EnableSearchTool declares the search_knowledge_base function so the
	// model can ground its answers. False yields an ungrounded assistant.
	EnableSearchTool bool
}

// Provider opens live voice sessions. Defined as an interface so the relay can
// be unit-tested against a fake without a real Gemini key.
type Provider interface {
	Connect(ctx context.Context, cfg SessionConfig) (Session, error)
}

// Session is one live voice connection. All Send* methods are safe for
// concurrent use; Events() is single-consumer.
type Session interface {
	Events() <-chan Event
	SendAudio(ctx context.Context, pcm []byte) error
	SendActivityStart(ctx context.Context) error
	SendActivityEnd(ctx context.Context) error
	// SendToolResponse replies to an EventToolCall. response is the JSON
	// object the model receives as the function result.
	SendToolResponse(ctx context.Context, id, name string, response map[string]any) error
	Close() error
}

// ─── Gemini wire types (server → us) ───────────────────────────────────────

type geminiServerMessage struct {
	ServerContent *geminiServerContent `json:"serverContent,omitempty"`
	ToolCall      *geminiToolCall      `json:"toolCall,omitempty"`
}

type geminiServerContent struct {
	ModelTurn           *geminiModelTurn     `json:"modelTurn,omitempty"`
	InputTranscription  *geminiTranscription `json:"inputTranscription,omitempty"`
	OutputTranscription *geminiTranscription `json:"outputTranscription,omitempty"`
	Interrupted         bool                 `json:"interrupted,omitempty"`
	TurnComplete        bool                 `json:"turnComplete,omitempty"`
}

type geminiModelTurn struct {
	Parts []geminiPart `json:"parts"`
}

type geminiPart struct {
	InlineData *geminiInlineData `json:"inlineData,omitempty"`
}

type geminiInlineData struct {
	MimeType string `json:"mimeType"`
	Data     string `json:"data"`
}

type geminiTranscription struct {
	Text string `json:"text"`
}

type geminiToolCall struct {
	FunctionCalls []geminiFunctionCall `json:"functionCalls"`
}

type geminiFunctionCall struct {
	ID   string         `json:"id"`
	Name string         `json:"name"`
	Args map[string]any `json:"args"`
}
