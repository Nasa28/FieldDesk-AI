package voicelive

import (
	"encoding/json"
	"testing"
)

func TestBuildVoiceSetupCoreFields(t *testing.T) {
	frame := buildVoiceSetup("models/test", "be helpful", "Kore", true)
	setup, ok := frame["setup"].(map[string]any)
	if !ok {
		t.Fatalf("frame missing setup object: %v", frame)
	}
	if setup["model"] != "models/test" {
		t.Errorf("model = %v, want models/test", setup["model"])
	}

	gen := setup["generationConfig"].(map[string]any)
	mods := gen["responseModalities"].([]string)
	if len(mods) != 1 || mods[0] != "AUDIO" {
		t.Errorf("responseModalities = %v, want [AUDIO]", mods)
	}
	voice := gen["speechConfig"].(map[string]any)["voiceConfig"].(map[string]any)["prebuiltVoiceConfig"].(map[string]any)["voiceName"]
	if voice != "Kore" {
		t.Errorf("voiceName = %v, want Kore", voice)
	}

	if _, ok := setup["inputAudioTranscription"]; !ok {
		t.Error("inputAudioTranscription missing")
	}
	if _, ok := setup["outputAudioTranscription"]; !ok {
		t.Error("outputAudioTranscription missing")
	}

	rt := setup["realtimeInputConfig"].(map[string]any)
	if rt["automaticActivityDetection"].(map[string]any)["disabled"] != true {
		t.Error("expected automaticActivityDetection.disabled=true (client-owned turns)")
	}

	// The frame must marshal cleanly to JSON for the WS write.
	if _, err := json.Marshal(frame); err != nil {
		t.Fatalf("setup frame not JSON-serializable: %v", err)
	}
}

func TestBuildVoiceSetupToolToggle(t *testing.T) {
	withTool := buildVoiceSetup("m", "", "Kore", true)["setup"].(map[string]any)
	if _, ok := withTool["tools"]; !ok {
		t.Error("expected tools when EnableSearchTool=true")
	}
	tools := withTool["tools"].([]map[string]any)
	decls := tools[0]["functionDeclarations"].([]map[string]any)
	if decls[0]["name"] != SearchToolName {
		t.Errorf("tool name = %v, want %s", decls[0]["name"], SearchToolName)
	}

	without := buildVoiceSetup("m", "", "Kore", false)["setup"].(map[string]any)
	if _, ok := without["tools"]; ok {
		t.Error("expected no tools when EnableSearchTool=false")
	}

	// Empty system prompt must be omitted, not sent as an empty instruction.
	if _, ok := without["systemInstruction"]; ok {
		t.Error("empty system prompt should omit systemInstruction")
	}
}

func TestDecodeFrameEvents(t *testing.T) {
	cases := []struct {
		name string
		raw  string
		want []EventType
	}{
		{
			name: "audio chunk",
			raw:  `{"serverContent":{"modelTurn":{"parts":[{"inlineData":{"mimeType":"audio/pcm;rate=24000","data":"AAAA"}}]}}}`,
			want: []EventType{EventAudioChunk},
		},
		{
			name: "input then output transcript with turn complete",
			raw:  `{"serverContent":{"inputTranscription":{"text":"hi"},"outputTranscription":{"text":"hello"},"turnComplete":true}}`,
			want: []EventType{EventInputTranscript, EventOutputTranscript, EventTurnComplete},
		},
		{
			name: "interrupted",
			raw:  `{"serverContent":{"interrupted":true}}`,
			want: []EventType{EventInterrupted},
		},
		{
			name: "tool call",
			raw:  `{"toolCall":{"functionCalls":[{"id":"c1","name":"search_knowledge_base","args":{"query":"psi"}}]}}`,
			want: []EventType{EventToolCall},
		},
		{
			name: "unknown frame drops",
			raw:  `{"somethingNew":{"x":1}}`,
			want: nil,
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := decodeFrame([]byte(tc.raw), nil)
			if len(got) != len(tc.want) {
				t.Fatalf("got %d events, want %d (%v)", len(got), len(tc.want), got)
			}
			for i := range got {
				if got[i].Type != tc.want[i] {
					t.Errorf("event[%d].Type = %d, want %d", i, got[i].Type, tc.want[i])
				}
			}
		})
	}
}

func TestDecodeFrameToolCallArgs(t *testing.T) {
	got := decodeFrame([]byte(`{"toolCall":{"functionCalls":[{"id":"c1","name":"search_knowledge_base","args":{"query":"confined space"}}]}}`), nil)
	if len(got) != 1 {
		t.Fatalf("want 1 event, got %d", len(got))
	}
	ev := got[0]
	if ev.ToolCallID != "c1" || ev.ToolName != SearchToolName {
		t.Errorf("tool id/name = %q/%q", ev.ToolCallID, ev.ToolName)
	}
	if ev.ToolArgs["query"] != "confined space" {
		t.Errorf("query arg = %v", ev.ToolArgs["query"])
	}
}
