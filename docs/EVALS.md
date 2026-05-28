# FieldDesk AI — Evals

We measure AI quality with a golden set, not vibes. Eval cases live in
`ai_eval_cases`; runs live in `ai_eval_runs`. The runner is in
`apps/worker/fielddesk_worker/evals/runner.py`.

## 1. Extraction Evals

Each `ai_eval_cases` row of kind `extraction` has:

- `input`: `{ "transcript": "..." }`
- `expected`: a `TicketExtraction` JSON document.
- `tags`: e.g. `["plumbing", "warranty", "spanish"]`.

For each case the runner produces a `TicketExtraction` and computes:

### Metrics

- **JSON validity rate**: did the model produce schema-valid JSON without re-prompt?
  - Target: ≥ 95%.
- **Required field completion rate**: fraction of required fields filled.
  - Target: ≥ 90% per field on the golden set.
- **Exact-match per field** (for enums / phones / names): expected == actual.
- **Soft-match per field** (for free-text like `issue_summary`): token F1 or LLM-judge similarity.
- **Confidence calibration**: bucket predicted confidence into deciles and compare to actual exact-match rate. A well-calibrated model has predicted ≈ observed accuracy.
- **Human correction rate**: from production data, fraction of fields a human edited after AI extraction.
  - Tracked from `human_reviews.correction` diffs against the original `ai_extractions.parsed_output`.

### Required Security Cases

The Phase 4c extraction golden set must include prompt-injection transcripts,
tagged with `["prompt-injection"]`, that try to override the schema,
confidence, `human_review_required`, or output format. Expected outputs should
preserve the real ticket facts and must not follow those embedded instructions.

## 2. RAG Evals

Each `ai_eval_cases` row of kind `rag` has:

- `input`: `{ "ticket": { ... extracted fields ... } }`
- `expected`: `{ "relevant_chunk_ids": ["..."] }` or `{ "relevant_doc_ids": ["..."] }`.

Metrics:

- **Retrieval hit rate @ k**: did at least one expected chunk appear in top-k? Track k=1, 3, 5.
- **Recall @ k**: fraction of expected chunks that appeared in top-k.
- **MRR (mean reciprocal rank)**: 1 / rank of first relevant chunk.
- **Answer groundedness**: when we generate an answer, fraction of claims that map to a retrieved chunk (LLM-judged).
- **Citation presence**: every generated suggestion cites at least one chunk id.
- **Human usefulness rating**: dispatchers rate suggestions 1–5; we aggregate the average.

### Required Security Cases

Phase 4.5 introduced a synthesis layer (`draft_ticket` job, `kind='recs'`
runs) that ingests ticket text and retrieved chunks into an LLM call. The recs golden set
in `evals/golden.py:GOLDEN_RECS_INJECTION_CASES` covers indirect prompt
injection: hostile ticket or chunk text that tries to plant fake parts into
`suggested_parts`, override `safety_checklist` entries, or coerce
`insufficient_context=false` on thin-context tickets. Each case names a
forbidden string; a pass means the string does NOT appear in the synthesis
output and the safety/context flags hold.

Run the recs suite alongside RAG retrieval evals:
`python -m fielddesk_worker.evals --tenant <uuid> --kind recs`.

## 3. Operational Evals (live, not golden)

These are computed from production tables on a rolling window:

- Job success rate by type and provider.
- Retry rate, distinguishing transient vs schema retries.
- p50 / p95 latency per stage.
- Cost per successful ticket.
- Provider error rate (provider_5xx / total calls).
- JSON-validation-failure rate over the last 24h.

## 4. Prompt Version Comparison

Every `ai_extractions` row stores `prompt_version` and `schema_version`. Every
`ai_eval_runs` row stores the same. To compare prompt v1 vs v2:

1. Tag both runs with the same `kind='extraction'` and the same golden-set version (via case `tags`).
2. Diff metrics between runs:
   - JSON validity delta.
   - Per-field completion delta.
   - Per-field exact-match delta.
   - Cost delta (sum of `ai_model_calls.cost_usd` attributable to the run).
   - Latency delta.
3. Promote a prompt only when it strictly dominates on quality without a material cost regression.

## 5. How to add a case

1. Write a minimal failing example you wish the system handled — voice note transcript + the ticket you wish it had produced.
2. Insert into `ai_eval_cases` with appropriate `kind` and `tags`.
3. Run the eval; verify it currently fails.
4. Iterate on prompt or pipeline. Re-run.
5. Lock the case in once it passes; it now guards against regressions.
