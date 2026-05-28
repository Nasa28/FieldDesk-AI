package ai

// Provider is a thin abstraction over an AI provider. The API does not
// call providers directly today — the Python worker does — but this
// interface gives us a place to hang model logging, cost accounting,
// fallbacks, and routing when the Go side needs to make calls.
type Provider interface {
	Name() string
	Kind() Kind
}

type Kind string

const (
	KindTranscription Kind = "transcription"
	KindLLM           Kind = "llm"
	KindEmbedding     Kind = "embedding"
)

// ModelCall is the canonical shape we log for every provider call.
// Every field maps 1:1 to the ai_model_calls table.
type ModelCall struct {
	Provider     string
	Model        string
	Kind         Kind
	InputTokens  int
	OutputTokens int
	DurationMS   int
	CostUSD      float64
	Success      bool
	ErrorClass   string
}
