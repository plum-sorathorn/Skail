# Defect Remediation Checklist

- [x] 0. Reconcile run IDs and plan ownership; establish new in-house token-cost evidence.
  - Evidence review completed across the original exports; the S5 plan belongs to run
    `46335ece-a442-4a0b-bb14-19f220c73846` and the later conflict question to S4 retry
    `ea102525-dc0f-412d-92f4-deddf12b6458`. The DevPass run now has a frozen-rate local ledger.
    Its campaign stop total is USD 1.006878588 through the interrupted S4 retry; four calls remain
    unresolved at call level but are conservatively settled. Provider billing is unverified.
  - Current policy is [ADR 0008](../docs/decisions/0008-in-house-token-cost-ledger.md): freeze
    model rates, price measured tokens locally, and include child calls in the parent run. Prior
    exports lack per-call tokens and remain historical estimates.
- [x] 1. Enforce explicit direct, no-delegation, no-write, exact-count, and named-agent-profile constraints at admission.
  - Evidence: `tests/unit/test_lead_intent.py`, `tests/contract/test_execution_decisions.py`, and focused `tests/integration/test_lead.py` regressions pass. Live S3 run `8054131c-c6c2-488d-bb55-3d5cf71fddc3` rejected the conflicting direct-mode plan. S4 run `360dbf83-cb8e-48c6-b7af-2c85a194436d` confirmed exact-count rejection; run `bb4cf4ac-a959-4a18-8696-50a2272c36a8` exposed the missing role guard. Commit `6b93eaf` enforces named profiles before plan admission. Live confirmation is pending.
- [x] 2. Bound repeated decision/tool loops and preserve uncertain call accounting.
  - Evidence: 32-call run limit is shared across lead/child middleware; exhaustion is emitted as `run.failed` with `run.model_call_limit_exhausted` before another provider call. `rtk pytest` focused regression suite: 43 passed; Ruff and Graphify update passed.
- [x] Checkpoint: invalid decisions and read-only loops terminate with one accurate outcome.
- [x] 3. Reproduce and fix cross-run plan/checkpoint/question ownership.
  - Reproduction proved that the old session thread carried a cancelled run's prompt into the next model request. Run-scoped threads, checkpoint thread metadata, pending-question guards, and TUI run/plan ownership state are implemented; focused recovery/UI tests pass. Interrupt cards now show owner suffixes. Commit `bf0513e` terminalizes unlaunched blocked plan rows; commit `3c5ab6e` waits for active-worker cleanup before TUI exit. A later run in the same session did not dispatch old task rows, but queue-prompt persistence across restart remains unproven. Live cancellation cleanup confirmation remains pending.
- [x] 4. Unify queue behavior across cancel, Ctrl+C, slash quit, and resume.
  - Evidence: 51 TUI interaction/command tests pass. Real Textual pilots cover `/cancel`, `/quit`, Ctrl+C, app exit, FIFO after success, queue non-restoration, and delayed active-worker cleanup across Ctrl+C, `/quit`, and host exit. A warning-as-error exit subset passes (4 tests). Queue clearing is visible.
- [x] Checkpoint: pending questions and queued prompts cannot silently cross run boundaries.
- [ ] 5. Separate clean user answers from structured verification and route evidence.
  - Offline implementation: shared TUI/print presenter, structured JSONL completion output, secret redaction, actionable empty/failed status copy, and a mounted Textual rendering pilot. Focused regression suite passes (110 tests); Ruff, mypy, and Graphify update pass. Keep unchecked pending a matching live S1 observation: the session export and checkpoint contain no final message, so the reported output's origin remains unknown.
- [ ] 6. Render normal questions as waiting, with question-specific controls and no tool error.
  - Offline implementation adds typed question events, keeps expected graph interrupts out of `tool.failed`, separates question answer/cancel from permission Approve/Reject, and shows session/run/plan owner suffixes. Focused offline regressions: 213 passed; the final owner-label/recovery subset: 16 passed. Ruff, mypy, and Graphify update pass. Live S6 confirmation remains pending.
- [x] 7. Audit earlier fixes with focused CLI and TUI checks.
  - Evidence: five catalog/list/refresh tests and four warning-as-error queue/cancel pilots pass; controller and real TUI cancellation checks show no framework traceback. Live confirmation for LIVE-001/003/004 and OUT-001/003 remains pending.
- [x] 8. Clear the three full offline suite failures.
  - Evidence: the no-credentials subprocess uses the null keyring backend, the initialization replay pilot waits asynchronously for its worker barrier, and the README assertion matches the current image masthead.
- [x] Checkpoint: Ruff, mypy, unit/contract, smoke, and full offline suite pass.
  - Verification after the exact-child, evaluation-gate, journal recovery, and plan-guidance fixes:
    Ruff passed; mypy found no issues in 126 source files; unit/contract passed (874 passed, 2
     skipped); smoke passed; full offline suite passed (1160 passed, 5 skipped). Commits: `06ebbc9`,
     `5d991a1`, `bf0513e`, `5eaadc4`, `6b93eaf`, `3c5ab6e`.
- [ ] 9. Re-run the remaining live scenarios with cumulative in-house token cost under USD 10.
  - In progress under the user's explicit best-effort waiver of a provider-side hard cap. The
    local stop point is USD 8.50 with a USD 10 ceiling. Read-only `GET /v1/key` reports DevPass
    Lite with USD 53.43 allowance remaining before the final S4 retry; this is plan allowance, not
     a spend ledger. Current local campaign stop total is USD 1.006878588. S3 intent and UTF-8
     rechecks pass; S4 count enforcement is confirmed live. The latest corrected S4 retry started
     run `7aa2bdab-ffea-470f-b8bc-6ab5e1e5e342` but was interrupted before a decision or plan; its
     Qwen call is unresolved and conservatively settled at USD 0.175416. Profile enforcement and
     child shutdown still need a successful live S4 completion; no plan or child was admitted in
     the latest run. The next run must use a new assignment, then S5-S7; S8 is conditional. Actual
     provider billing remains unknown.
    Actual provider billing is unknown because no independent billing baseline/delta is available.
  - Future runs use export schema version 2 `provider_calls` and `model_usage`; compare local
    per-model calculations with the TUI's lead-plus-child run total after each scenario. The
    LLM Gateway CLI is removed from the procedure.
- [ ] Update `BUGS.md`, `OUTPUT_MISFORMATS.md`, `RUN_LOG.md`, and `COSTS.csv` with verified outcomes.
