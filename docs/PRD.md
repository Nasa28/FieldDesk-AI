# FieldDesk AI PRD

## 1. Product Summary

FieldDesk AI is a voice-to-ticket system for field service teams. It helps technicians, dispatchers, and operations teams turn messy voice notes into structured job tickets.

The system transcribes voice notes, extracts ticket details, retrieves relevant company knowledge, suggests next actions, and routes uncertain outputs to human review.

## 2. One-liner

An AI system that turns technician voice notes into structured job tickets with transcription, extraction, RAG, human review, cost tracking, reliability controls, and monitoring.

## 3. Target Users

### Primary user

Field service technician who records job updates, customer complaints, repair notes, and follow-up actions by voice.

### Secondary user

Dispatcher or operations manager who reviews tickets, assigns work, checks AI confidence, and corrects mistakes.

### Admin user

Company owner or operations lead who manages users, company documents, AI settings, cost limits, and reliability dashboards.

## 4. Problem

Field service teams lose important job information because technicians often communicate through voice notes, calls, WhatsApp messages, and informal updates.

This creates problems:

- Dispatchers manually rewrite voice notes into tickets.
- Job details are incomplete or inconsistent.
- Technicians forget parts, safety steps, or customer preferences.
- Managers lack visibility into AI quality, cost, and failure rates.
- AI outputs are risky if they are accepted without review or measurement.

## 5. Product Goals

### Core goals

- Convert voice notes into structured job tickets.
- Reduce manual ticket creation time.
- Improve job detail completeness.
- Add human review for uncertain AI outputs.
- Retrieve relevant company knowledge for each ticket.
- Track AI cost, latency, failures, and accuracy.
- Make the system reliable enough to feel production-grade.

### Portfolio goals

- Prove applied AI engineering skill.
- Show production backend design.
- Demonstrate RAG, structured extraction, evals, observability, retries, and cost management.
- Create a project strong enough for startup AI Engineer applications.

## 6. Non-goals for MVP

- Native mobile app.
- Real-time phone call transcription.
- Full CRM replacement.
- Technician scheduling optimization.
- Billing and payments.
- Offline-first mobile workflow.
- Custom-trained speech model.

## 7. MVP Scope

### MVP must include

- User authentication.
- Company workspace.
- Audio upload.
- Audio transcription.
- AI extraction into structured ticket fields.
- Editable ticket review screen.
- Human review queue.
- AI confidence score.
- Model call logging.
- Cost tracking per transcription, extraction, and RAG call.
- Retry handling for failed AI jobs.
- Failure monitoring dashboard.
- Basic document upload for RAG.
- Document chunking and embedding.
- Relevant knowledge suggestions for each ticket.

### MVP should not include

- Complex permissions beyond admin and member.
- Full mobile app.
- Deep integrations with external CRMs.
- Automated technician assignment.
- Voice cloning or generated voice output.

## 8. Core User Flow

1. Technician uploads or records a voice note.
2. System stores the audio file.
3. Background worker transcribes the audio.
4. AI extracts structured ticket fields from the transcript.
5. System validates the JSON output.
6. System calculates confidence.
7. System retrieves relevant company documents using RAG.
8. System creates a draft ticket.
9. Dispatcher reviews, edits, and approves the ticket.
10. Approved ticket becomes the final job ticket.
11. All model calls, costs, failures, retries, and human corrections are logged.

## 9. Ticket Fields

The AI should extract:

- Customer name.
- Customer phone.
- Service address.
- Trade type.
- Issue summary.
- Detailed description.
- Priority.
- Preferred visit time.
- Required skills.
- Suggested parts.
- Safety concerns.
- Warranty mention.
- Follow-up questions.
- Confidence score.
- Human review required flag.

## 10. AI Capabilities

### 10.1 Speech-to-text

The system transcribes uploaded audio into text.

Initial option:

- Hosted transcription API for speed.

Future option:

- Local faster-whisper or whisper.cpp service.

### 10.2 Structured extraction

The system converts transcripts into validated JSON.

The extraction output must match a strict schema.

Invalid JSON should never create a final ticket automatically.

### 10.3 RAG

The system retrieves company knowledge related to each ticket.

Possible knowledge sources:

- SOPs.
- Safety procedures.
- Price books.
- Warranty policies.
- Past ticket notes.
- Parts catalog.
- Troubleshooting guides.

RAG output should suggest:

- Similar past tickets.
- Relevant SOPs.
- Parts to bring.
- Safety checklist.
- Follow-up questions.
- Possible diagnosis.

### 10.4 Human review

AI output should be treated as draft until approved.

Human review is required when:

- Confidence is below threshold.
- JSON validation fails.
- Required fields are missing.
- The transcript is unclear.
- The model reports uncertainty.
- The task involves sensitive customer or safety information.

## 11. Reliability Requirements

### 11.1 Job processing

AI work should run in background jobs.

Each voice note should create jobs for:

- Transcription.
- Extraction.
- RAG retrieval.
- Ticket draft creation.

Each job should have statuses:

- Pending.
- Processing.
- Succeeded.
- Failed.
- Retrying.
- Needs review.

### 11.2 Retries

Failed jobs should retry with limits.

Retry strategy:

- Retry transient errors.
- Use exponential backoff.
- Stop after max retry count.
- Send failed jobs to review queue.
- Log final failure reason.

Retryable failures:

- Timeout.
- Rate limit.
- Temporary provider error.
- Network error.
- Worker crash.

Non-retryable failures:

- Unsupported file type.
- Empty audio.
- Invalid tenant access.
- Corrupt file.
- Missing required object.

### 11.3 Idempotency

The same audio upload should not create duplicate tickets if a job retries.

Each job should have an idempotency key.

### 11.4 Fallbacks

If primary model fails, system should support fallback behavior:

- Retry same model once.
- Use backup model if configured.
- Route to manual review if all AI steps fail.

## 12. Cost Management

The system should track cost at every AI step.

Track:

- Transcription cost.
- Extraction model cost.
- Embedding cost.
- RAG answer cost.
- Total cost per ticket.
- Total cost per tenant.
- Cost by model.
- Cost by user.

Controls:

- Monthly tenant budget.
- Daily tenant budget.
- Max cost per ticket.
- Model routing by task type.
- Cheaper model for simple extraction.
- Stronger model for complex or low-confidence cases.
- Disable expensive RAG summaries when budget is exceeded.

Admin should see:

- Cost today.
- Cost this month.
- Average cost per ticket.
- Most expensive tickets.
- Failed calls that still cost money.

## 13. Measurability and Evals

The system should measure AI quality, not guess.

### Extraction metrics

Track:

- JSON validity rate.
- Required field completion rate.
- Human correction rate.
- Confidence calibration.
- Extraction accuracy on test cases.
- Average review time.

### RAG metrics

Track:

- Retrieval hit rate.
- Top-k document relevance.
- Answer groundedness.
- Citation presence.
- Human usefulness rating.

### Operational metrics

Track:

- Transcription latency.
- Extraction latency.
- RAG latency.
- End-to-end ticket creation time.
- Job success rate.
- Retry rate.
- Failure rate.
- Provider error rate.
- Cost per successful ticket.

## 14. Monitoring and Failure Visibility

The admin dashboard should show:

- Failed jobs.
- Jobs stuck in processing.
- Retry counts.
- Provider errors.
- Average latency.
- Cost spikes.
- Low-confidence tickets.
- Tickets waiting for human review.
- Model output validation failures.

Failure alerts should trigger when:

- AI failure rate crosses threshold.
- Queue backlog grows too high.
- Average latency crosses threshold.
- Daily cost exceeds budget threshold.
- JSON validation failure rate increases.
- A provider is unavailable.

## 15. Data Model Draft

Core tables:

- tenants.
- users.
- voice_notes.
- transcripts.
- job_tickets.
- ai_extractions.
- ai_model_calls.
- ai_jobs.
- ai_job_attempts.
- documents.
- document_chunks.
- embeddings.
- rag_queries.
- human_reviews.
- ai_eval_cases.
- ai_eval_runs.
- tenant_ai_budgets.

## 16. Suggested Tech Stack

### Backend

Go, chi, sqlc, Goose, PostgreSQL.

### AI worker

Python FastAPI worker or Python job worker.

### Frontend

Next.js.

### Storage

Cloudflare R2, Supabase Storage, or S3-compatible storage.

### Queue

Start with PostgreSQL job table.

Upgrade later to Redis queue if needed.

### Vector search

Start with pgvector.

### Transcription

Hosted Whisper-compatible API for MVP.

### LLM

Hosted LLM with structured output support.

### Embeddings

Hosted embeddings first.

Local embeddings later if cost or privacy becomes important.

## 17. Success Metrics

MVP is successful when:

- A user uploads audio and gets a structured ticket.
- At least 90% of test voice notes produce valid JSON.
- At least 80% of required fields are filled correctly on sample test cases.
- Failed jobs are visible and retryable.
- Cost per ticket is tracked.
- Human corrections are stored.
- RAG suggestions reference relevant documents.
- Admin dashboard shows model calls, latency, failures, retries, and cost.

## 18. Demo Script

1. Log in as dispatcher.
2. Upload a technician voice note.
3. Show transcription status.
4. Show extracted draft ticket.
5. Show AI confidence and required review flag.
6. Show RAG suggestions from uploaded SOPs.
7. Edit and approve ticket.
8. Open AI logs.
9. Show model cost, latency, retries, and provider used.
10. Open failure dashboard and show how failed jobs are handled.

## 19. Build Phases

### Phase 1: Voice-to-ticket MVP

- Auth.
- Workspace.
- Audio upload.
- Transcription.
- Structured extraction.
- Editable ticket draft.

### Phase 2: Reliability layer

- Background jobs.
- Retries.
- Job attempts.
- Failure states.
- Idempotency keys.
- Manual review fallback.

### Phase 3: Cost and observability

- Model call logs.
- Token and cost tracking.
- Latency tracking.
- Failure dashboard.
- Tenant budgets.

### Phase 4: RAG

- Document upload.
- Chunking.
- Embeddings.
- Vector search.
- Ticket-specific recommendations.

### Phase 5: Evals

- Golden test cases.
- Extraction eval runner.
- RAG eval runner.
- Prompt version comparison.

## 20. Open Decisions

- Use Go-only backend with Python worker, or Go backend plus separate Python AI service?
- Start with PostgreSQL queue or Redis queue?
- Which transcription provider should be used first?
- Which LLM provider should be used first?
- Should demo data focus on plumbing, HVAC, electrical, or all three?
- Should the frontend be built first or after the API foundation?
