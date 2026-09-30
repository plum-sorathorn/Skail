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

The 2026-09-26 same-run retest accepted `JSON` in run
`e12b7b3e-e2a9-402a-a0bb-8e9e34c14c96`, then emitted `run.completed` with output status
`waiting_for_user` and a stale “A blocking question was asked...” summary. No exporter or test
file was written. A red/green regression now covers this structured status variant; the live run
remains failed and needs a new post-fix confirmation.

The next same-run retry `b4235f5b-0c92-419b-9803-adbc4f00c8ff` accepted `JSON`, then emitted
`run.completed` with output status `blocked` but a stale summary beginning “Blocked for user input:
Awaiting your selection”. It still wrote no exporter or test. The guard now recognizes that
blocked-prefixed waiting summary so it cannot be recorded as a completed run.

The S5 exports record explorer tasks as failed and retry routing as `auto_ineligible`, but their
`task.failed` payloads have no safe failure category or validation field path. They therefore do not
distinguish provider errors, malformed child results, result-validation failures, routing
ineligibility, and ordinary task failures.

## Decision

1. An accepted question answer belongs to its waiting run. If the resumed final result has status
   `waiting_for_user` or its summary still says that an answer is pending, including “Waiting for
   your answer” or “Awaiting your selection,” Skail ends that run as blocked with
   `execution.answer_not_continued`. It records a concise diagnostic result and does not emit
   `run.completed` for a final result that is still waiting. Skail does not start a hidden provider
   retry.
2. Child `TaskResult` values may carry optional `failure_category` and `validation_path` fields. These
   fields are runtime-owned; values supplied in model-authored JSON are discarded.
3. Task terminal events may carry the same safe fields. Categories are limited to
   `provider_error`, `malformed_result`, `result_validation`, `routing_ineligible`, `budget_blocked`,
   and `task_failure`. A validation path contains only known schema field names and array indexes.
   Raw model output and provider exception text are not copied into task events.
4. The existing repeated-call detector continues to compare canonicalized tool name and arguments.
   The S6 export does not include tool arguments, so the 21 `ls` calls cannot be classified as
   identical from preserved evidence. No detector threshold or signature behavior changes here.
5. Execution-plan schema rejections report safe field paths and distinguish invalid scalar values
   from invalid JSON types without echoing submitted values or validator messages. A string outside
   an enum is `invalid_value`; a value of the wrong JSON type is `invalid_type`. Validation paths
   retain only allowlisted field names and nonnegative indexes through 99; all other indexes are
   rendered as `<index>`.
6. When no decision has been admitted, two decision validation rejections exhaust the bounded
   repair allowance. If no operational work succeeded, initial and resumed completion terminate
   blocked with `execution.decision_exhausted`. An admitted decision or completed operational work
   prevents this guard from converting the result to blocked.
7. Plan-repair diagnostics preserve a submitted valid mode: direct-mode plans are told to omit the
   plan and revision, discovery plans are told to remain read-only, and planned plans retain planned
   guidance. Diagnostics name allowed effect-scope values without echoing submitted values. Writer
   TaskResults may use the runtime `file_digest` tool for a current file reference. The digest
   verifies bytes only and must not be described as test execution evidence.

## Consequences

- A model that returns stale waiting text after an accepted answer produces an actionable blocked
  result instead of a false success. The operator can submit a new instruction after that run ends.
- Future child failures are diagnosable from session events without exporting unrestricted child
  output or provider exception text.
- Existing schema-v2 exports retain their original payloads and remain inconclusive about the S5
  explorer causes and S6 raw final message.

## Verification

- `tests/integration/test_phase10c_resume_dispatch.py` reproduces the two accepted-answer/stale-
  waiting prefixes, the structured `waiting_for_user` status, and the observed blocked-prefixed
  stale summary; each must end blocked without `run.completed`.
- `tests/contract/test_question_resume_contract.py` proves the accepted same-run JSON path writes
  only the exporter and its focused test, then returns one completed result.
- `tests/contract/test_task_result.py` covers malformed JSON, schema field errors, explicit task
  failure, and runtime ownership of diagnostic fields.
- `tests/integration/test_task_graph.py` covers provider and route failure categories.
- `tests/integration/test_lead.py` verifies a malformed child result reaches the persisted task event
  without including the raw child output.
- `tests/integration/test_phase10c_resume_dispatch.py` proves an accepted answer followed by two
  rejected decisions cannot complete without an admitted decision or operational work.
- `tests/contract/test_execution_decisions.py` covers direct-mode-preserving diagnostics and safe
  effect-scope guidance; `tests/integration/test_task_graph.py` covers runtime file digests.
