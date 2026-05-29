// Package voicelive is a thin client for Google Gemini's Live API
// (bidirectional audio over WebSocket). It is a trimmed adaptation of the
// pattern proven in the recruiter-ai-interview-platform repo: there is no
// Google Go SDK for the Live API, so we speak raw JSON frames over a
// WebSocket to BidiGenerateContent.
//
// Scope is deliberately small — audio in, audio + transcripts out, plus one
// function-call tool for knowledge-base grounding. Interview-specific
// concerns (session resumption, segment rollover, goAway handling) are out
// of scope: voice Q&A turns are short.
package voicelive

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"sync"
	"sync/atomic"
	"time"

	"github.com/coder/websocket"
)

const geminiLiveEndpoint = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"

// ErrProviderUnavailable wraps any failure to reach or set up Gemini so the
// relay can return a clean "voice is down" message rather than a raw error.
var ErrProviderUnavailable = errors.New("voicelive: provider unavailable")

// Config is the process-wide Gemini setup.
type Config struct {
	APIKey      string
	Model       string // e.g. "models/gemini-2.5-flash-native-audio-preview-09-2025"
	Voice       string // default voice name; per-session override via SessionConfig
	Logger      *slog.Logger
	DialTimeout time.Duration
}

// GeminiProvider is the long-lived factory the server holds onto.
type GeminiProvider struct {
	apiKey      string
	model       string
	voice       string
	log         *slog.Logger
	dialTimeout time.Duration
}

// NewGemini validates config and returns the provider. The only hard
// requirement is an API key; the WS dial happens per session in Connect.
func NewGemini(cfg Config) (*GeminiProvider, error) {
	if cfg.APIKey == "" {
		return nil, errors.New("voicelive: APIKey is required")
	}
	log := cfg.Logger
	if log == nil {
		log = slog.Default()
	}
	dt := cfg.DialTimeout
	if dt <= 0 {
		dt = 10 * time.Second
	}
	voice := cfg.Voice
	if voice == "" {
		voice = "Kore"
	}
	return &GeminiProvider{
		apiKey:      cfg.APIKey,
		model:       cfg.Model,
		voice:       voice,
		log:         log,
		dialTimeout: dt,
	}, nil
}

// Connect dials Gemini, sends the setup frame, waits for setupComplete, then
// returns a session whose Events() channel is fed by a reader goroutine.
func (p *GeminiProvider) Connect(ctx context.Context, cfg SessionConfig) (Session, error) {
	dialCtx, cancel := context.WithTimeout(ctx, p.dialTimeout)
	defer cancel()

	url := fmt.Sprintf("%s?key=%s", geminiLiveEndpoint, p.apiKey)
	conn, _, err := websocket.Dial(dialCtx, url, &websocket.DialOptions{HTTPClient: http.DefaultClient})
	if err != nil {
		return nil, fmt.Errorf("%w: dial: %v", ErrProviderUnavailable, err)
	}
	// Gemini audio frames can be large; give the reader generous headroom.
	conn.SetReadLimit(8 * 1024 * 1024)

	voice := cfg.VoiceName
	if voice == "" {
		voice = p.voice
	}

	setup := buildVoiceSetup(p.model, cfg.SystemPrompt, voice, cfg.EnableSearchTool)
	setupBytes, err := json.Marshal(setup)
	if err != nil {
		_ = conn.Close(websocket.StatusInternalError, "marshal")
		return nil, fmt.Errorf("voicelive: marshal setup: %w", err)
	}
	if err := conn.Write(dialCtx, websocket.MessageText, setupBytes); err != nil {
		_ = conn.Close(websocket.StatusInternalError, "write setup")
		return nil, fmt.Errorf("%w: write setup: %v", ErrProviderUnavailable, err)
	}

	_, raw, err := conn.Read(dialCtx)
	if err != nil {
		_ = conn.Close(websocket.StatusInternalError, "read setup")
		return nil, fmt.Errorf("%w: read setup: %v", ErrProviderUnavailable, err)
	}
	var probe map[string]json.RawMessage
	if err := json.Unmarshal(raw, &probe); err != nil {
		_ = conn.Close(websocket.StatusInternalError, "decode setup")
		return nil, fmt.Errorf("voicelive: decode setup: %w", err)
	}
	if _, ok := probe["setupComplete"]; !ok {
		_ = conn.Close(websocket.StatusInternalError, "no setupComplete")
		return nil, fmt.Errorf("%w: no setupComplete: %s", ErrProviderUnavailable, string(raw))
	}

	sess := &geminiSession{
		conn:    conn,
		log:     p.log,
		events:  make(chan Event, 64),
		closeCh: make(chan struct{}),
	}
	go sess.readLoop()
	sess.events <- Event{Type: EventSetupComplete}
	return sess, nil
}

// buildVoiceSetup is a pure function (unit-tested) that produces the Gemini
// setup frame: audio-only output, the configured prebuilt voice, input/output
// transcription, client-owned turn boundaries (no server VAD — the browser
// drives push-to-talk), and optionally the knowledge-base search tool.
func buildVoiceSetup(model, systemPrompt, voiceName string, enableSearchTool bool) map[string]any {
	gen := map[string]any{
		"responseModalities": []string{"AUDIO"},
		"speechConfig": map[string]any{
			"voiceConfig": map[string]any{
				"prebuiltVoiceConfig": map[string]any{
					"voiceName": voiceName,
				},
			},
		},
	}
	setup := map[string]any{
		"model":            model,
		"generationConfig": gen,
		"realtimeInputConfig": map[string]any{
			// The browser owns turn boundaries (hold-to-talk). Disable Gemini's
			// automatic VAD so a thinking pause isn't read as "done speaking".
			"activityHandling": "NO_INTERRUPTION",
			"automaticActivityDetection": map[string]any{
				"disabled": true,
			},
			"turnCoverage": "TURN_INCLUDES_ONLY_ACTIVITY",
		},
		// Presence enables transcription; the config objects have no fields.
		"inputAudioTranscription":  map[string]any{},
		"outputAudioTranscription": map[string]any{},
	}
	if systemPrompt != "" {
		setup["systemInstruction"] = map[string]any{
			"parts": []map[string]any{{"text": systemPrompt}},
		}
	}
	if enableSearchTool {
		setup["tools"] = []map[string]any{{
			"functionDeclarations": []map[string]any{{
				"name":        SearchToolName,
				"description": "Search the company's uploaded knowledge-base documents (SOPs, manuals, safety procedures) for passages relevant to the technician's question. Call this before answering any factual question.",
				"parameters": map[string]any{
					"type": "object",
					"properties": map[string]any{
						"query": map[string]any{
							"type":        "string",
							"description": "A focused search query derived from the technician's spoken question.",
						},
					},
					"required": []string{"query"},
				},
			}},
		}}
	}
	return map[string]any{"setup": setup}
}

// ─── session ────────────────────────────────────────────────────────────────

type geminiSession struct {
	conn    *websocket.Conn
	log     *slog.Logger
	events  chan Event
	closeCh chan struct{}

	writeMu sync.Mutex
	closed  atomic.Bool
}

func (s *geminiSession) Events() <-chan Event { return s.events }

func (s *geminiSession) SendAudio(ctx context.Context, pcm []byte) error {
	if s.closed.Load() {
		return errors.New("voicelive: session closed")
	}
	frame := map[string]any{
		"realtimeInput": map[string]any{
			"audio": map[string]any{
				"mimeType": "audio/pcm;rate=16000",
				"data":     base64.StdEncoding.EncodeToString(pcm),
			},
		},
	}
	return s.writeJSON(ctx, frame)
}

func (s *geminiSession) SendActivityStart(ctx context.Context) error {
	return s.sendActivity(ctx, "activityStart")
}

func (s *geminiSession) SendActivityEnd(ctx context.Context) error {
	return s.sendActivity(ctx, "activityEnd")
}

func (s *geminiSession) sendActivity(ctx context.Context, field string) error {
	if s.closed.Load() {
		return errors.New("voicelive: session closed")
	}
	return s.writeJSON(ctx, map[string]any{
		"realtimeInput": map[string]any{field: map[string]any{}},
	})
}

func (s *geminiSession) SendToolResponse(ctx context.Context, id, name string, response map[string]any) error {
	if s.closed.Load() {
		return errors.New("voicelive: session closed")
	}
	return s.writeJSON(ctx, map[string]any{
		"toolResponse": map[string]any{
			"functionResponses": []map[string]any{{
				"id":       id,
				"name":     name,
				"response": response,
			}},
		},
	})
}

func (s *geminiSession) writeJSON(ctx context.Context, frame map[string]any) error {
	data, err := json.Marshal(frame)
	if err != nil {
		return fmt.Errorf("voicelive: marshal frame: %w", err)
	}
	s.writeMu.Lock()
	defer s.writeMu.Unlock()
	return s.conn.Write(ctx, websocket.MessageText, data)
}

func (s *geminiSession) Close() error {
	if !s.closed.CompareAndSwap(false, true) {
		return nil
	}
	close(s.closeCh)
	return s.conn.Close(websocket.StatusNormalClosure, "session ended")
}

func (s *geminiSession) readLoop() {
	defer close(s.events)
	ctx := context.Background()
	for {
		_, raw, err := s.conn.Read(ctx)
		if err != nil {
			if !s.closed.Load() {
				s.events <- Event{Type: EventError, Err: err}
			}
			return
		}
		s.dispatch(raw)
	}
}

// dispatch decodes one Gemini server frame into 0+ normalized events.
// Unrecognized shapes are dropped rather than crashing the session.
func (s *geminiSession) dispatch(raw []byte) {
	for _, ev := range decodeFrame(raw, s.log) {
		s.events <- ev
	}
}

// decodeFrame is the pure core of dispatch — split out so it is unit-testable
// without a live socket.
func decodeFrame(raw []byte, log *slog.Logger) []Event {
	var msg geminiServerMessage
	if err := json.Unmarshal(raw, &msg); err != nil {
		if log != nil {
			log.Warn("voicelive: decode frame", "error", err)
		}
		return nil
	}
	var out []Event
	if sc := msg.ServerContent; sc != nil {
		if sc.Interrupted {
			out = append(out, Event{Type: EventInterrupted})
		}
		if sc.ModelTurn != nil {
			for _, part := range sc.ModelTurn.Parts {
				if part.InlineData == nil || part.InlineData.Data == "" {
					continue
				}
				mime := part.InlineData.MimeType
				if mime == "" {
					mime = "audio/pcm;rate=24000"
				}
				out = append(out, Event{Type: EventAudioChunk, AudioPCM: part.InlineData.Data, AudioMIME: mime})
			}
		}
		if sc.InputTranscription != nil && sc.InputTranscription.Text != "" {
			out = append(out, Event{Type: EventInputTranscript, TranscriptText: sc.InputTranscription.Text})
		}
		if sc.OutputTranscription != nil && sc.OutputTranscription.Text != "" {
			out = append(out, Event{Type: EventOutputTranscript, TranscriptText: sc.OutputTranscription.Text})
		}
		if sc.TurnComplete {
			out = append(out, Event{Type: EventTurnComplete})
		}
	}
	if msg.ToolCall != nil {
		for _, fc := range msg.ToolCall.FunctionCalls {
			out = append(out, Event{
				Type:       EventToolCall,
				ToolCallID: fc.ID,
				ToolName:   fc.Name,
				ToolArgs:   fc.Args,
			})
		}
	}
	return out
}
