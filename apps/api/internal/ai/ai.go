package ai

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
