package jobs

type Type string

const (
	TypeTranscribe Type = "transcribe"
	TypeExtract    Type = "extract"
	TypeEmbed      Type = "embed"
	TypeRAG        Type = "rag"
	TypeDraft      Type = "draft_ticket"
)

type Status string

const (
	StatusPending     Status = "pending"
	StatusProcessing  Status = "processing"
	StatusSucceeded   Status = "succeeded"
	StatusFailed      Status = "failed"
	StatusRetrying    Status = "retrying"
	StatusNeedsReview Status = "needs_review"
)

type Enqueuer interface {
	Enqueue(ctx Context, job NewJob) (string, error)
}

type Context interface{}

type NewJob struct {
	TenantID       string
	Type           Type
	IdempotencyKey string
	Payload        map[string]any
}
