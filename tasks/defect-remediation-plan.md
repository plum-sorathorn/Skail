# Defect Remediation Plan: Live Agentic Validation

> Historical implementation record. The current comprehensive follow-up is
> [the 2026-09-24 remediation plan](remediation-2026-09-24-plan.md). Keep the historical
> evidence below for traceability; its earlier gates and test counts are superseded.

The operator prompts, scenario acceptance checks, spend gates, and evidence procedure for the
remaining interactive run are in `tasks/live-agentic-test-plan.md`.

## Goal and scope

Close every issue in `out/live-agentic/BUGS.md` and `OUTPUT_MISFORMATS.md`, including defects
marked fixed that still need end-to-end confirmation. Restore the unfinished direct, parallel,
planned, interrupt, safety, and output scenarios using the in-house token-cost ledger defined in
[ADR 0008](../docs/decisions/0008-in-house-token-cost-ledger.md). The previous provider-billing
gate below records the historical stop decision; future validation follows
`tasks/live-agentic-test-plan.md` without the LLM Gateway CLI. This document makes no paid calls.

The logs were reviewed against the current source and exported run events. Two evidence
corrections govern the work:

1. The USD 0.4376813 figure is Skail-exported usage plus conservative estimates. External provider
   billing was not captured, so actual spend is unknown. `COSTS.csv` now leaves provider billing
   columns blank.
2. The S5 plan was admitted in run `46335ece-a442-4a0b-bb14-19f220c73846`; the conflict question
   arose in later S4 retry run `ea102525-dc0f-412d-92f4-deddf12b6458`. The in-memory TUI queue
   is cleared on quit. There is no evidence that a queued prompt survived restart. Treat LIVE-006
   as a P2 cross-run context or resume investigation; elevate it to P1 only if an earlier plan
   actually changes later run authority or causes duplicate work.

## Coverage and current confidence

| Issue | Current assessment | Repair or proof needed |
|---|---|---|
| LIVE-001 catalog with no prices | Offline list/refresh tests distinguish unavailable and unpriced entries; current provider catalog/prices remain unverified | Confirm current prices and freeze them per assignment before live calls |
| LIVE-002 direct request admitted a plan | Runtime guard implemented and offline regressions pass; live confirmation pending | Enforce explicit direct/no-delegation intent at admission |
| LIVE-003 / OUT-001 cancellation traceback | Offline controller and real Textual slash-cancel checks pass without traceback; live-provider confirmation pending | Confirm cancellation during a bounded live call |
| LIVE-004 / OUT-003 coroutine warning | Queue shutdown is unified across slash cancel/quit, Ctrl+C, and app exit; real Textual tests pass; live confirmation pending | Route every quit path through one queue shutdown sequence |
| LIVE-005 long tool and repair loops | Run-wide call cap and repeated decision/tool failure bounds implemented; live confirmation pending | Add a run-scoped call/turn boundary and visible terminal outcome |
| LIVE-006 later run cites earlier plan | Offline reproduction confirmed shared checkpoint context leakage; run-scoped fix is covered, live confirmation pending | Trace checkpoint thread, plan ownership, and pending question across runs |
| LIVE-007 / OUT-004 question shown as tool failure | Offline fix suppresses expected graph-interrupt failures and emits a typed question event; real `ask_user` errors still fail; live S6 confirmation pending | Confirm question wait and resume with in-house call accounting |
| OUT-002 internal criteria in final answer | Offline presentation path fixed; the exact S1 model response is absent from its export/checkpoint, so origin and live status remain unverified | Preserve structured evidence while presenting a clean answer; confirm with a matching live observation |
| OUT-005 question labeled approval | Offline UI separates question answer/cancel controls from permission approval controls and displays owner suffixes; live confirmation pending | Confirm question and approval cards in the live TUI |

Task 0 evidence review is complete for the exported sessions: all ten `session-*.json` files were
checked, including S5 plan admission in run `46335ece-a442-4a0b-bb14-19f220c73846` and the later
S4 retry question in run `ea102525-dc0f-412d-92f4-deddf12b6458`. The export does not prove queue
persistence across restart. Provider-side usage history and a capped test key remain pending; no
paid validation call has been made during remediation.

A final read-only provider CLI status check found no dashboard session. The account usage and key
budget commands therefore could not provide an independent billing baseline or a provider-enforced
cap. The prior USD 0.4376813 remains Skail-exported usage plus estimates, not provider spend.

Task 1 implementation is complete offline. Run-specific controls enforce direct/no-delegation,
no-write, and exact agent-count constraints before plan admission. Focused unit, contract, and
integration regressions pass. The live S2 confirmation remains pending.

Task 2 implementation is complete offline. Each run has a 32-call ceiling shared across lead and
children, checked before the next provider call; exhaustion emits `run.failed` with
`run.model_call_limit_exhausted`. Repeated decision errors now reach the existing failure monitor.
Focused loop, decision, child, and accounting regressions pass. Live confirmation remains pending.

Task 3 reproduced cross-run context leakage. A cancelled planned run followed by a separate
instruction on the same session previously reused the session checkpoint thread and included the
old prompt in the new model input. Checkpoints now record run-scoped thread IDs; resumed runs retain
their owning thread, while new runs start fresh. A pending question blocks direct run creation, and
the TUI rejects new composer prompts until resolution. This reproduction did not restart the
process, so it provides no evidence that the in-memory queue survives restart. Task 6 adds run and
plan owner suffixes to pending interrupt cards.

Task 4 implementation is complete offline. Successful foreground runs retain FIFO dispatch; whole-run
cancel and shutdown clear queued prompts with visible copy. Slash commands bypass the prompt queue,
and no follow-up worker is started during cancellation or app exit. The queue is transient and is
not restored in a new TUI instance. Pilot tests cover slash `/cancel`, slash `/quit`, Ctrl+C, app
exit, successful FIFO, and non-restoration; no provider calls were made.

The original raw LEAD JSON report is covered by the output task as a regression case. Do not
delete information by stripping arbitrary lines from model text; keep structured evidence in the
appropriate panel or export and show a clean answer in the chat.

## Implementation order

### 0. Establish a reliable baseline and cost evidence

Inspect the last live exports and journal rows without another provider call. Record one row per
run with its assignment, accepted decision, plan owner, tool failures, terminal status, and cost
authority. Historical provider charges remain unknown; do not retroactively label Skail's
estimates as billed spend. For future calls, capture measured tokens and prices frozen on each
assignment, plus unresolved call IDs. Use the current live test plan's spend gate.

Acceptance:

- `COSTS.csv` distinguishes historical Skail exports from new locally calculated token costs
  and unresolved calls; none is presented as verified provider billing.
- Each live defect cites the correct run ID and evidence, and unproven cause claims are marked as
  hypotheses.
- The cumulative test ledger includes lead and child calls at their frozen per-model prices;
  `/budget` and exported call totals agree.

Verification: inspect `session-S1.json` through `session-S5-final.json`; use export schema
version 2 for new call/token evidence. No model generation is needed for the historical review.

### 1. Enforce explicit execution intent at the admission boundary

Translate clear user directives such as “do this yourself,” “do not delegate,” “do not edit,” and
“use exactly two agents” into run-scoped constraints before the first provider call. Validate
`execution_decision` and task admission against those constraints. A conflicting model decision
must fail with one stable, actionable code and no plan, child, or write admitted. Keep normal
adaptive planning available when the user has not constrained the mode. Validate nested decision
payloads without silently accepting contradictory outer/inner fields.

Likely files: `src/skail/runtime/run_controller.py`, `src/skail/runtime/decisions.py`,
`src/skail/agents/lead.py`, focused contract/integration tests, and the affected feature contract.

Acceptance:

- S2's direct/no-delegation prompt cannot admit a planned decision or child task.
- S4's exactly-two instruction either admits two disjoint scoped children or returns a clear
  constraint error before launch.
- Nested decision metadata with conflicting mode/objective is rejected; one valid nested form is
  accepted exactly once.

Verification: contract tests for the decision gate and integration tests for plan/task admission.

### 2. Bound paid model and tool loops

Add a run-scoped maximum for model turns and a separate cap on repeated identical tool/decision
failures. Stop with a structured `run.failed` or `run.blocked` result and a stable diagnostic code;
do not add a new lifecycle event type unless the event contract is updated. Preserve the last
safe state, finalize known usage, and leave ambiguous calls explicitly unresolved. Show a concise
terminal explanation in the TUI. Boundaries must count lead and child calls without changing the
maximum two child attempts per task.

Likely files: `src/skail/runtime/run_controller.py`, `src/skail/runtime/model_middleware.py`,
`src/skail/runtime/decisions.py`, `src/skail/tui/app.py`, and tests around repeated tool calls.

Acceptance:

- A repeated invalid decision terminates after the configured repair allowance with no further
  paid model call.
- A read-only tool loop terminates at a deterministic cap, with one terminal run event and no
  false success.
- Cancellation during a provider call cannot silently convert uncertain cost into a verified
  actual; the reservation/uncertainty remains visible.

Verification: deterministic loop and cancellation tests, then one bounded interactive smoke test
after Task 0's in-house price and cost gate.

### 3. Make run and plan ownership explicit across resume

Reproduce LIVE-006 with a cancelled planned run followed by a new write request in the same
session. Inspect LangGraph's `thread_id`, restored checkpoint, current run ID, pending question,
and accepted plan ID. Decide from the existing session contract whether a new prompt continues
the prior plan or starts a new run; make that choice explicit in runtime state and TUI copy.
Prevent an unresolved question from being treated as a fresh prompt, and prevent a new run from
silently inheriting a cancelled plan's execution authority. Do not clear durable user questions
merely to make the conflict disappear.

Likely files: `src/skail/runtime/run_controller.py`, `src/skail/sessions/checkpoints.py`,
`src/skail/tui/app.py`, and recovery tests.

Acceptance:

- A cancelled plan cannot relaunch its terminal nodes or constrain an unrelated new run without an
  explicit continuation decision.
- Quit/resume presents the same pending question once, with its owning run and plan.
- A new prompt while a question is pending is queued or rejected visibly; it is never passed as an
  answer or silently mixed into the checkpoint.

Verification: integration tests with a real checkpointer and a TUI pilot test; compare exports
before and after resume.

### 4. Complete queue and shutdown semantics

Unify Ctrl+C, slash `/quit`, window close, and `/cancel` around one queue lifecycle. Keep FIFO
behavior while a foreground run succeeds; when it is cancelled, decide whether queued prompts are
discarded or held for explicit user action and display that state. Avoid constructing a follow-up
coroutine until the app is ready to schedule it. Keep queue state and conversation context separate.

Likely files: `src/skail/tui/app.py`, `src/skail/tui/projection.py`, and TUI interaction tests.

Acceptance:

- No queued prompt runs after cancellation or quit without a visible user action.
- Every exit path produces no unawaited-coroutine warning; FIFO success path still runs each
  follow-up once.
- Resume does not invent or duplicate in-memory queued prompts.

Verification: exercise real Textual quit/cancel events, not only a direct call to a helper.

### 5. Separate user answers from verification evidence

Review the S1 checkpointed lead message and the `RunResult.output` construction to identify whether
OUT-002 is model-authored prose or a serializer leak. Define a single presentation rule for the
chat, print, and JSONL surfaces: the chat/print answer is human readable; route, criteria, and
verification details remain available in structured evidence. Preserve intentional user-requested
technical details. Keep the existing clean JSON answer extraction, and test unknown or malformed
JSON as a readable error or literal only when appropriate.

Likely files: `src/skail/runtime/run_controller.py`, `src/skail/tui/app.py`,
`src/skail/tui/projection.py`, output tests, and CLI/feature documentation if the public contract
changes.

Acceptance:

- A structured LEAD response shows its answer once in chat; JSONL retains structured data.
- S1's short explanation contains the file/function citation without `Passed: True`, criterion
  serialization, Python `repr`, or duplicate final text.
- Blocked/failed runs show an actionable outcome rather than an empty or fabricated success.

Verification: contract tests using real final-message shapes plus a TUI pilot rendering check.

Offline implementation is complete: TUI and print share the same answer presenter, completion JSONL
retains structured output, registered secrets are redacted before display, and empty or unsuccessful
TUI outcomes have explicit status copy. A mounted Textual pilot confirms the answer appears once
without serialized verification fields. The S1 export for run
`bec67311-fc21-4faf-a474-1f9c4fb4f8f6` has no transcript/output field; its terminal checkpoint
`1f1b6b15-b500-67e5-800a-646a33ab08e0` has no `messages` channel. The recorded S1 text therefore
cannot be attributed to model-authored prose or the former renderer from preserved artifacts. Keep
OUT-002 open until a matching live observation captures the raw response and rendered answer.

### 6. Render questions, approvals, and waiting accurately

Carry a typed interrupt kind through runtime events and the TUI projection. Treat a normal
`ask_user` graph interrupt as a wait transition, not `tool.failed`. Label a question as a question
with an answer control, and reserve Approve/Reject controls for permission decisions. Keep the
pending state visible across resume and clear `WAITING` only after the recorded answer/rejection
is acknowledged.

Likely files: `src/skail/runtime/run_controller.py`, `src/skail/tools/assembly.py`,
`src/skail/tui/projection.py`, `src/skail/tui/widgets/interrupts.py`, and interrupt tests.

Acceptance:

- OUT-004 has no error row for an expected question; an actual failed `ask_user` still reports an
  error.
- OUT-005 shows question-specific title, answer action, and cancellation copy; permission
  approvals still show Approve/Reject.
- S6 resumes one question and one attempt, without replaying the completed provider call.

Verification: runtime event contract test, Textual pilot, and recovery integration test.

Offline implementation carries `InterruptKind` and stable IDs in question events, suppresses
`GraphInterrupt` from tool-failure telemetry while preserving actual tool exceptions, and emits the
answer event only after `QuestionStore` accepts the response. The TUI renders separate question and
permission cards, validates listed choices, keeps `WAITING` until the accepted answer/cancellation,
and shows session/run/plan owner suffixes. Recovery and Textual pilot coverage passes. Live S6 and
matching S4 confirmation remain pending.

### 7. Verify earlier fixes

Audit LIVE-001, LIVE-003, LIVE-004, OUT-001, and OUT-003 against their committed fixes. Add only
the missing checks: fresh catalog refresh/list behavior and documentation, real TUI cancellation
without traceback, and slash quit with a queued follow-up.

Acceptance:

- Those five fixed entries have an end-to-end passing check or are reopened with concrete evidence.
- The catalog command distinguishes unpriced configuration from a qualified priced catalog.
- Ctrl+C and slash quit both leave a clean terminal and no queued coroutine warning.

Verification: focused CLI, cancellation, and TUI tests plus one local interactive quit check.

Offline audit passed: five catalog/list/refresh cases cover missing snapshots, unpriced selection,
successful refresh, and empty-refresh preservation; a real Textual slash-cancel test confirms clean
cancellation copy without a framework traceback; and slash cancel/quit, Ctrl+C, and app-exit queue
pilots pass with runtime warnings treated as errors. Their linked live defects remain pending because
provider-side billing baseline and spend controls are not available.

### 8. Clear the offline test failures

Resolve the three full-suite failures reported at the end of the live run: no-credentials
diagnostic mismatch, the initialization replay test that failed in the full suite but passed alone,
and README logo/test disagreement. Check the recent logo commit and current canonical mark before
changing either side.

Acceptance:

- The no-credentials path reports the missing credential/provider action rather than a misleading
  route failure.
- The initialization test uses event synchronization and passes reliably in the full suite.
- The README logo and logo assertion agree with the current intended mark.

Verification: focused tests for each issue, then the repository's Ruff, mypy, unit/contract,
smoke, and full offline suite in CI order.

Task 8 is complete offline. The no-credentials E2E subprocess uses the null keyring backend so host
credentials cannot change its diagnostic. The initialization replay pilot waits asynchronously for
its worker barrier, and the README masthead assertion matches the current image. Final gates:
Ruff passed; mypy found no issues in 126 source files; unit/contract passed with 865 passed and 2
skipped; smoke passed; full offline suite passed with 1136 passed and 5 skipped.

### 9. Re-run the live matrix with in-house token accounting

Use a clean disposable fixture commit and one durable session. Complete S2, both S3 reviews, S4
two-child concurrency/FIFO, S5 checkpoint/revision, S6 question resume, S7 boundary denial, and
optional S8 natural escalation. Record exact model IDs, assignments, plan revisions, child peak
concurrency, terminal states, output shapes, changed paths, independent fixture tests, and
per-model token/cost evidence after every scenario. Keep the sub-USD-10 in-house ceiling and stop
rules; do not describe the token calculation as verified provider billing.

Acceptance:

- Every scenario receives pass, fail, blocked-as-expected, skipped, or not-exercised with evidence.
- Cumulative in-house lead-plus-child token costs stay below USD 10; interrupted or missing-usage
  calls remain unresolved and block another paid scenario until safely accounted for.
- The open defects and output misformats are closed only after matching live observations, not
  because unit tests pass.

Verification: session exports with per-call tokens and frozen prices, TUI observations,
  `git diff --check`, and
independently rerun fixture tests.

## Dependencies and checkpoints

```text
0 evidence/billing ────────────────────────────────────────┐
1 intent/admission ──> 2 bounded loops ──┐                │
3 run/plan ownership ─> 4 queue lifecycle ├─> 9 live retest
5 answer rendering ───────────────────────┤                │
6 interrupt rendering/recovery ───────────┤                │
7 fixed-case audit ──> 8 offline gates ──┘────────────────┘
```

Checkpoint after Tasks 1-2: malformed decisions and repeated calls stop predictably. Checkpoint
after Tasks 3-4: resume and queue never mix run ownership. Checkpoint after Tasks 5-8: user output
and full offline quality gates pass. Task 9 starts only after the in-house pricing and spend
gate in `tasks/live-agentic-test-plan.md`.

Do not force escalation or change the fixture to make S8 fail. Any public event/status, CLI, or
interrupt contract change needs its spec/ADR update in the same implementation task.

## Next execution pass after the offline repairs

The September 22 run is the latest live-agentic matrix in `out/live-agentic`. Tasks 1, 2, 4, 7,
and 8 are complete offline; Tasks 3, 5, and 6 have offline repairs but still need matching live
observations. No later live run proves those repairs. Use the following order for the remaining
work, without repeating completed implementation solely to satisfy a test scenario:

1. **Establish cost authority (Task 0).** Refresh the model catalog, record per-model rates and
   revision, and start a fresh in-house campaign ledger. Keep prior interrupted calls labelled
   unknown; do not fold Skail's prior estimates into verified spend. The operator waived the
   provider-side hard cap for the DevPass-key rerun; follow the live plan's local stop rules.
2. **Retest the repaired paths (Tasks 3, 5, 6, and 9).** In a disposable repository, run S2 direct
   intent, S3 model switch and bounded review, S4 exactly-two-child orchestration and FIFO queue,
   S5 plan admission/cancel followed by an unrelated run, S6 question/approval/quit/resume, and S7
   safety denial. Exercise S8 only if a natural escalation occurs. Export each session immediately
   and record run ID, plan ID, exact model, terminal state, changed paths, output shape, and the
   in-house token-cost delta before the next paid scenario. A result is confirmed only when the live
   event stream and TUI both match the relevant acceptance criteria above.
3. **If a defect recurs, repair its owning seam and add a failing regression first.** For direct
   intent or child-count violations, inspect `run_controller.py` and `decisions.py` admission. For
   repeated calls, inspect the run-wide counter in `model_middleware.py` and terminal event path in
   `run_controller.py`. For old plans or questions appearing in new runs, compare checkpoint
   `thread_id`, run ID, and plan ID in `checkpoints.py`, `run_controller.py`, and TUI pending state;
   do not attribute this to queue persistence without a restart reproduction. For quit/cancel
   warnings, test the real Textual shutdown paths in `app.py`. For answer or question misformats,
   compare raw model output, structured `run.completed` payload, TUI projection, and the rendered
   widget. Keep expected graph interrupts out of `tool.failed` while preserving real tool errors.
   Update the corresponding feature contract or ADR in the same change if the public behavior
   changes, then run focused tests and the full offline gate in repository order.
4. **Close evidence (Task 9).** Update `BUGS.md`, `OUTPUT_MISFORMATS.md`, `RUN_LOG.md`, and
   `COSTS.csv` with observed pass/fail/blocked results, token counts, frozen rates, and local
   cost deltas. Leave defects open where the original output cannot be reproduced. The cumulative
   in-house token-cost total must remain below USD 10; actual provider billing is unverified.
