# Defect Remediation Checklist

- [x] 0. Reconcile run IDs and plan ownership; establish new in-house token-cost evidence.
  - Evidence review completed across the original exports; the S5 plan belongs to run
    `46335ece-a442-4a0b-bb14-19f220c73846` and the later conflict question to S4 retry
    `ea102525-dc0f-412d-92f4-deddf12b6458`. The DevPass run now has a frozen-rate local ledger.
    Its reconciled campaign stop total is USD 2.594404734 through six original S5 runs, five S5 follow-up runs/probes, four S6 probes, and S7;
    USD 1.810620734 is measured-token pricing and USD 0.783784 is conservatively estimated. Ten
    calls remain unresolved at call level but are conservatively settled. Provider billing is
    unverified.
  - Current policy is [ADR 0008](../docs/decisions/0008-in-house-token-cost-ledger.md): freeze
    model rates, price measured tokens locally, and include child calls in the parent run. Prior
    exports lack per-call tokens and remain historical estimates.
- [x] 1. Enforce explicit direct, no-delegation, no-write, exact-count, and named-agent-profile constraints at admission.
  - Evidence: `tests/unit/test_lead_intent.py`, `tests/contract/test_execution_decisions.py`, and focused `tests/integration/test_lead.py` regressions pass. Live S3 run `8054131c-c6c2-488d-bb55-3d5cf71fddc3` rejected the conflicting direct-mode plan. S4 run `360dbf83-cb8e-48c6-b7af-2c85a194436d` confirmed exact-count rejection; run `bb4cf4ac-a959-4a18-8696-50a2272c36a8` exposed the missing role guard. Commit `6b93eaf` enforces named profiles before plan admission. The latest S4 plans were admitted with `implementer` task profiles, but no child assignment completed; dispatch confirmation remains pending.
  - Follow-up evidence: S5 runs `464af106-673d-4246-9686-cb948d6c5c7c` and `cd1bcae5-4e25-42fe-8a50-f733ae9a0543` completed without matching planned decisions; the latter claimed child agents had launched although no plan or child tasks existed. Explicit planned mode is enforced at initial completion and after resume. Run `b8d63cc7-2399-43c0-9337-44601eaf22b8` showed child-scoped “do not delegate further” was misread as direct-only; the parser now scopes that phrase correctly, covered by a red/green test.
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
  - Offline implementation adds typed question events, keeps expected graph interrupts out of `tool.failed`, separates question answer/cancel from permission Approve/Reject, and shows session/run/plan owner suffixes. A run-scoped requirement permits only `ask_user` before an accepted answer, survives resume, and opens conditional writes afterward. New regressions verify the restored answer field gets keyboard focus and a question never inherits a prior run's plan label.
  - Live run `e3786699-ea65-46d7-8a5c-b51844089029` raised question `38d7d947-7ff6-4725-ba70-7d3ca1c377b6`. After quit/resume the same card appeared once, without the old S5 plan label; the focused input accepted `JSON`. That run completed with its earlier blocked summary and no workspace changes. A fresh continuation, `26a86890-a34f-4664-aa28-843e2d752b84`, created only `exporter.py` and `test_exporter.py` but failed at the 32-call limit after repeated `ls` checks. The operator focused test passed (2 passed); full fixture suite was 9 passed and 3 existing parser/report/integration `NotImplementedError` failures. S6 cost is USD 0.131608 of USD 0.75, leaving USD 0.618392. LIVE-030/OUT-012 remain open, so S6 is incomplete.
- [x] 7. Audit earlier fixes with focused CLI and TUI checks.
  - Evidence: five catalog/list/refresh tests and four warning-as-error queue/cancel pilots pass; controller and real TUI cancellation checks show no framework traceback. The two-case non-TTY resume guard is covered by `test_non_tty_resume_without_prompt_is_rejected_before_execution`. Lead guidance now says the coordinator launches admitted plan nodes and the lead must not call `task()` to recreate them. Live confirmation for LIVE-001/003/004 and OUT-001/003 remains pending.
- [x] 8. Clear the three full offline suite failures.
  - Evidence: the no-credentials subprocess uses the null keyring backend, the initialization replay pilot waits asynchronously for its worker barrier, and the README assertion matches the current image masthead.
- [x] Checkpoint: Ruff, mypy, unit/contract, smoke, and full offline suite pass.
  - Latest verification after the live-question answer-focus and plan-ownership repairs:
    Ruff passed; mypy found no issues in 126 source files; unit/contract passed (892 passed, 2 skipped);
    smoke passed; full offline suite passed (1176 passed, 5 skipped).
- [ ] 9. Re-run the remaining live scenarios with cumulative in-house token cost under USD 10.
  - The user waived a provider-side hard cap and set a best-effort USD 10 ceiling; the normal
    in-house stop remains USD 8.50. Three earlier ledger rows were corrected because they omitted
    measured calls when charging estimates for separate calls. Six original S5 runs plus a TUI
    help probe, a quoted-prompt conflict, a plan-schema retry, an admitted-plan explorer retry, and
    the S6 probes, S7, and final S5 retry have added USD 0.573422454 (USD 0.395510454 measured plus
    USD 0.177912 conservatively estimated). The campaign stop is USD 2.594404734: USD 1.810620734 measured plus
    USD 0.783784 estimated.
    Ten calls lack reliable token usage and are conservatively settled; do not replay them. This
    leaves USD 5.905595266 to the local stop and USD 7.405595266 to the campaign ceiling. S4 used
    USD 1.512342744 of its USD 1.60 allocation, leaving USD 0.087657256. S5 used USD 0.438850454
    of USD 2.25, leaving USD 1.811149546. S5 remains incomplete: four admitted plans ended with
    explorer failures before the checkpoint, one lead call was ambiguous, one plan was rejected for
    missing resource scopes, two runs falsely completed without a plan, and one schema repair failed.
    No accepted discoveries, checkpoint, revision, or implementation was produced.
  - Offline child-result guidance is committed as 935ae49. The explorer prompt now includes profile
    guidance and the shared JSON TaskResult evidence contract. The lead's minimal plan example now
    includes read effect_scope, non-empty resource_scopes, and checkpoint dependencies; its
    regression failed before the change and passes afterward. Explicit planned intent now survives
    question resume and cannot finish successfully without a matching decision. Latest gates after
    the question UI focus/ownership fixes pass: Ruff, mypy, unit/contract (892 passed, 2 skipped),
    smoke, and full suite (1176 passed, 5 skipped).
  - The idle TUI resume displayed route events already present in its prior export; it started no new
    run and added no cost. The user confirmed DevPass approves Skail. S6 remains incomplete after the
    accepted answer failed to continue in the same run; the fresh continuation created the files but
    exhausted its 32-call limit. S7 passed: Skail denied the outside write and no outside file exists
    (USD 0.010002 locally). S8 was not exercised because the fixture integration test has no natural
    concurrency defect; no failure was forced. Actual provider billing remains unknown.
  - Future runs compare locally recomputed per-call costs with schema-v2 provider_calls and
    model_usage; the LLM Gateway CLI remains removed from the procedure.
- [ ] Update `BUGS.md`, `OUTPUT_MISFORMATS.md`, `RUN_LOG.md`, and `COSTS.csv` with verified outcomes.
