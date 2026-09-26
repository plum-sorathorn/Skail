# ADR 0009: Preserve truthful question completion and safe task diagnostics

Status: Accepted  
Date: 2026-09-24  
Depends on: [ADR 0006](./0006-adaptive-execution-and-release-boundaries.md)

## Context

The S6 session export recorded an accepted `JSON` answer followed by `run.completed` carrying the
previous “Waiting for your answer” summary, with no workspace changes. The export preserves the
terminal result and model-call order, but not the raw final model message, so it does not establish
whether the model repeated the text or checkpoint state replayed it.
The later live run `5a216e69-9126-49b0-849f-9811d5ba0a35` reproduced the same failure with
“Awaiting your selection of exporter format” after the accepted answer. Commit `7b54772`
extended the deterministic regression and guard to that observed wording; a same-run live
confirmation of the repair is still pending.

The S5 exports record explorer tasks as failed and retry routing as `auto_ineligible`, but their
`task.failed` payloads have no safe failure category or validation field path. They therefore do not
distinguish provider errors, malformed child results, result-validation failures, routing
ineligibility, and ordinary task failures.

## Decision

1. An accepted question answer belongs to its waiting run. If the resumed final result still says
   it is waiting, including “Waiting for your answer” or “Awaiting your selection,” Skail ends
   that run as blocked with `execution.answer_not_continued`. It records a concise diagnostic
   result and does not emit `run.completed` for a final result that still says it is waiting.
   Skail does not start a hidden
   provider retry.
2. Child `TaskResult` values may carry optional `failure_category` and `validation_path` fields. These
   fields are runtime-owned; values supplied in model-authored JSON are discarded.
3. Task terminal events may carry the same safe fields. Categories are limited to
   `provider_error`, `malformed_result`, `result_validation`, `routing_ineligible`, `budget_blocked`,
   and `task_failure`. A validation path contains only known schema field names and array indexes.
   Raw model output and provider exception text are not copied into task events.
4. The existing repeated-call detector continues to compare canonicalized tool name and arguments.
   The S6 export does not include tool arguments, so the 21 `ls` calls cannot be classified as
   identical from preserved evidence. No detector threshold or signature behavior changes here.

## Consequences

- A model that returns stale waiting text after an accepted answer produces an actionable blocked
  result instead of a false success. The operator can submit a new instruction after that run ends.
- Future child failures are diagnosable from session events without exporting unrestricted child
  output or provider exception text.
- Existing schema-v2 exports retain their original payloads and remain inconclusive about the S5
  explorer causes and S6 raw final message.

## Verification

- `tests/integration/test_phase10c_resume_dispatch.py` reproduces both observed
  accepted-answer/stale-waiting prefixes and requires one blocked result for each.
- `tests/contract/test_question_resume_contract.py` proves the accepted same-run JSON path writes
  only the exporter and its focused test, then returns one completed result.
- `tests/contract/test_task_result.py` covers malformed JSON, schema field errors, explicit task
  failure, and runtime ownership of diagnostic fields.
- `tests/integration/test_task_graph.py` covers provider and route failure categories.
- `tests/integration/test_lead.py` verifies a malformed child result reaches the persisted task event
  without including the raw child output.
