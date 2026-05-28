package jobs

// Type enumerates the kinds of AI jobs FieldDesk runs.
type Type string

const (
	TypeTranscribe Type = "transcribe"
	TypeExtract    Type = "extract"
	TypeEmbed      Type = "embed"
	TypeRAG        Type = "rag"
	TypeDraft      Type = "draft_ticket"
)

// Status enumerates the lifecycle states of an AI job.
type Status string

const (
	StatusPending     Status = "pending"
	StatusProcessing  Status = "processing"
	StatusSucceeded   Status = "succeeded"
	StatusFailed      Status = "failed"
	StatusRetrying    Status = "retrying"
	StatusNeedsReview Status = "needs_review"
)

// Enqueuer is implemented by anything that can push a job onto the queue.
// For MVP this writes into the ai_jobs table; later it could publish to
// Redis or another broker.
type Enqueuer interface {
	Enqueue(ctx Context, job NewJob) (string, error)
}

// Context is a placeholder; replace with context.Context once enqueuing is wired.
type Context interface{}

// NewJob is the input payload for enqueuing a new job.
type NewJob struct {
	TenantID       string
	Type           Type
	IdempotencyKey string
	Payload        map[string]any
}
