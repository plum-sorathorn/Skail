# Defect Remediation Checklist

Current sequence and acceptance checks: [2026-09-24 remediation plan](remediation-2026-09-24-plan.md).
The completed items below are historical offline milestones; unchecked live confirmations
remain open until matching evidence is recorded.

- [x] 0. Reconcile run IDs and plan ownership; establish new in-house token-cost evidence.
  - Evidence review completed across the original exports; the S5 plan belongs to run
    `46335ece-a442-4a0b-bb14-19f220c73846` and the later conflict question to S4 retry
    `ea102525-dc0f-412d-92f4-deddf12b6458`. The DevPass run now has a frozen-rate local ledger.
    Seven latest schema-v2 exports contain 328 unique provider-call IDs. The 296 priced calls in
    the current local campaign total USD 1.803778734; ten calls lack tokens and are conservatively
    settled at USD 0.783784. A separate USD 0.006842 carry-forward adjustment preserves the
    user-authorized campaign stop at USD 2.594404734 after correcting one duplicated CSV scenario
    row. The new `out/live-agentic/CALL_COST_AUDIT.csv` records every call calculation. Sixteen
    older measured calls reprice to USD 0.173399080 in-house, while six older calls lack tokens;
    these remain outside the current campaign stop. Provider billing is unverified.
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
  - Live run `e3786699-ea65-46d7-8a5c-b51844089029` raised question `38d7d947-7ff6-4725-ba70-7d3ca1c377b6`. After quit/resume the same card appeared once, without the old S5 plan label; the focused input accepted `JSON`. That run completed with its earlier blocked summary and no workspace changes. A fresh continuation, `26a86890-a34f-4664-aa28-843e2d752b84`, created only `exporter.py` and `test_exporter.py` but failed at the 32-call limit after repeated `ls` checks. The operator focused test passed (2 passed); full fixture suite was 9 passed and 3 existing parser/report/integration `NotImplementedError` failures. S6 cost is USD 0.131608 of USD 0.75, leaving USD 0.618392. Offline regressions now block a stale “Waiting for your answer” result after an accepted answer; LIVE-030/OUT-012 live confirmation remains pending and S6 is incomplete.
- [x] 7. Audit earlier fixes with focused CLI and TUI checks.
  - Evidence: five catalog/list/refresh tests and four warning-as-error queue/cancel pilots pass; controller and real TUI cancellation checks show no framework traceback. The two-case non-TTY resume guard is covered by `test_non_tty_resume_without_prompt_is_rejected_before_execution`. Lead guidance now says the coordinator launches admitted plan nodes and the lead must not call `task()` to recreate them. Live confirmation for LIVE-001/003/004 and OUT-001/003 remains pending.
- [x] 8. Clear the three full offline suite failures.
  - Evidence: the no-credentials subprocess uses the null keyring backend, the initialization replay pilot waits asynchronously for its worker barrier, and the README assertion matches the current image masthead.
- [x] Checkpoint: Ruff, mypy, unit/contract, smoke, and full offline suite pass.
  - Final required verification after the relative package-artifact path regression:
    Ruff passed; mypy found no issues in 126 source files; unit/contract passed (900 passed, 2 skipped);
    `python scripts/smoke.py` passed; full suite passed three times (1185 passed, 5 skipped each).
    After the S3 config-revision regression and fix in `b278324`, the required gates passed again in
    order; the full suite reported 1186 passed, 5 skipped.
    After the pre-assignment terminalization regression and fix in `84f798d`, the same ordered gates
    passed again; unit/contract reported 900 passed, 2 skipped and the full suite 1187 passed,
    5 skipped.
    `scripts/package_check.py` built, inspected, and installed a real wheel and sdist; packaging tests
    reused that wheel and passed (9 passed). The regression first failed when `verify_installation`
    received a relative wheel path, then passed after the path was resolved before changing cwd.
    After the S4 scope repair in `d92b4b9`, ordered gates passed again (full suite 1188 passed,
    5 skipped). After the S6 stale-selection repair in `7b54772`, ordered gates passed again:
    Ruff, mypy (126 files), unit/contract (900 passed, 2 skipped), smoke, and full suite
    (1184 passed, 5 skipped in the recorded gate). A fresh `rtk pytest -q` audit passed
    1189 with 5 skipped. The count difference is unresolved; compare collected cases before
    treating the earlier 166.71s median as a current-revision measurement.
- [ ] 9. Re-run the remaining live scenarios with cumulative in-house token cost under USD 10.
  - The user waived a provider-side hard cap and set a best-effort USD 10 ceiling; the normal
    in-house stop remains USD 8.50. Three earlier ledger rows were corrected because they omitted
    measured calls when charging estimates for separate calls. Six original S5 runs plus a TUI
    help probe, a quoted-prompt conflict, a plan-schema retry, an admitted-plan explorer retry, and
    the S6 probes, S7, and final S5 retry have added USD 0.573422454 (USD 0.395510454 measured plus
    USD 0.177912 conservatively estimated). The campaign stop remains USD 2.594404734: USD
    1.803778734 measured, USD 0.783784 estimated, and USD 0.006842 retained as a reconciliation
    buffer.
    Ten calls lack reliable token usage and are conservatively settled; do not replay them. This
    left USD 5.905595266 to the local stop and USD 7.405595266 to the campaign ceiling at that
    historical checkpoint. S4 used
    USD 1.512342744 of its USD 1.60 allocation, leaving USD 0.087657256. S5 used USD 0.432008454
    of USD 2.25, leaving USD 1.817991546 after per-call recalculation. S5 remains incomplete: four admitted plans ended with
    explorer failures before the checkpoint, one lead call was ambiguous, one plan was rejected for
    missing resource scopes, two runs falsely completed without a plan, and one schema repair failed.
    No accepted discoveries, checkpoint, revision, or implementation was produced.
  - Offline child-result guidance is committed as 935ae49. The explorer prompt now includes profile
    guidance and the shared JSON TaskResult evidence contract. The lead's minimal plan example now
    includes read effect_scope, non-empty resource_scopes, and checkpoint dependencies; its
    regression failed before the change and passes afterward. Explicit planned intent now survives
    question resume and cannot finish successfully without a matching decision. Prior gates after
    the remediation fixes passed: Ruff, mypy, unit/contract (900 passed, 2 skipped), smoke, and three
    full suites (1185 passed, 5 skipped each). After S3 exposed a config-revision mismatch, the new
    red/green regression and fix in `b278324` passed Ruff, mypy (126 files), unit/contract (900 passed,
    2 skipped), smoke, and full suite (1186 passed, 5 skipped) in order. The pre-assignment failure
    terminalization regression and fix in `84f798d` then passed the same gates; full suite reported
    1187 passed, 5 skipped. The same-run stale-answer guard is fixed offline; its matching live
    recheck remains open.
  - The idle TUI resume displayed route events already present in its prior export; it started no new
    run and added no cost. The user confirmed DevPass approves Skail. S6 remains incomplete after the
    accepted answer produced a stale waiting summary and no workspace changes; an offline regression
    now blocks that false completion. The fresh continuation created the files but exhausted its
    32-call limit. Its exported tool names were inspected in order, but arguments are absent; no
    identical-call cause is assigned and the detector remains unchanged. S7 passed: Skail denied the outside write and no outside file exists
    (USD 0.010002 locally). The historical S8 campaign was not exercised because the fixture had
    no natural concurrency defect; no failure was forced. The current S8 attempt used the baseline
    parser failure in a fresh task: its first child result failed validation at
    `$.artifacts.0.kind`, and its sole retry assignment was blocked as `model_disabled`. The child
    focused tests passed, but its result was not integrated; S8 was exercised and remains
    incomplete. Actual provider billing remains unknown.
  - Future runs compare locally recomputed per-call costs with schema-v2 provider_calls and
    model_usage; the LLM Gateway CLI remains removed from the procedure.
- [ ] Update `BUGS.md`, `OUTPUT_MISFORMATS.md`, `RUN_LOG.md`, and `COSTS.csv` with verified outcomes.

## Offline baseline and independent mechanism map

Before suite optimization, three serial runs of `python -m pytest -q --durations=40` passed the
same 1,176 tests with 5 skips. Wall times were 164.17s, 159.42s, and 173.13s (164.17s median);
pytest-reported times were 160.82s, 156.24s, and 169.79s (160.82s median). The measured slices
were unit/contract 108.29s, integration 67.43s, E2E 37.68s, security 9.97s, packaging 8.41s, and
mounted TUI 64.11s. Logs are `out/live-agentic/offline-baseline-{1,2,3}.txt` and
`out/live-agentic/slice-baseline-*.txt`.

| Mechanism | Focused evidence | Independent boundary evidence |
|---|---|---|
| Provider normalization and accounting | `tests/contract/test_provider_contract.py`, `test_llmgateway.py`, `test_devpass.py`; `tests/unit/test_model_usage_events.py`, `test_toolcall_missing_usage_repro.py` | `tests/integration/test_assignment.py`, `test_provider_fallback.py` |
| Budget reservation and settlement | `tests/unit/test_budget.py`, `test_run_call_budget.py`, `test_estimates.py` | `tests/integration/test_assignment.py`, `test_budget_concurrency.py`; `tests/security/test_crash_recovery_and_reservations.py` |
| Task and plan ownership/results | `tests/unit/test_task_registry.py`, `test_execution_plans.py`; `tests/contract/test_execution_decisions.py`, `test_task_result.py` | `tests/integration/test_lead.py`, `test_plan_persistence.py`, `test_plan_blocked_reasons.py`, `test_delegation_controls.py` |
| Concurrency and leases | `tests/unit/test_leases.py`, `test_scheduler.py` | `tests/integration/test_scheduler_concurrency.py`, `test_write_leases.py`, `test_delegation_controls.py` |
| Trust, path, command, and secret boundaries | `tests/unit/test_trust.py`, `test_execution_policy.py`, `test_redaction.py` | `tests/security/test_workspace_boundaries.py`, `test_command_injection_and_approvals.py`, `test_extension_trust_and_secrets.py`, `test_resolved_credential_canaries.py` |
| Checkpoint, question, and resume | `tests/unit/test_run_controller_diagnostics.py`, `test_tui_interactions.py` | `tests/contract/test_question_resume_contract.py`; `tests/integration/test_recovery.py`, `test_questions.py`, `test_phase10c_resume_dispatch.py` |
| CLI and installed entry points | `tests/contract/test_cli.py` | `tests/e2e/test_cli_e2e.py` launches `python -m skail.cli.main` in isolated workspaces |
| Textual mounted behavior | `tests/unit/test_tui_interactions.py`, `test_tui_overlays.py` | `tests/integration/test_tui_commands.py`, `test_tui_shell.py`, `test_tui_boot_pilot.py` exercise real keyboard, focus, queue, question, and resume paths |
| Wheel and source distribution contents | `tests/unit/test_packaging.py` | `scripts/package_check.py` builds, inspects, and installs real artifacts in a clean environment |
| Deterministic evaluations | `tests/unit/test_eval_runner.py`, `test_eval_evidence.py`, `test_eval_paired_matrix.py` | `tests/contract/test_eval_fixtures.py` pins fixture/runner assumptions |
| Release scripts | `tests/unit/test_release_check.py` | `scripts/smoke.py` and `scripts/release_check.py` run as command-line gates |

The baseline bottlenecks were release/evaluation `--help` imports (15.84s in the unit/contract
slice), removed-alias subprocesses (8.96s in E2E), real wheel build and inspection (6.02s), and the
parallel-versus-serial evaluation fixture (5.09s). Mounted TUI tests were profiled separately; pure
formatting tests already live in unit modules, while mounted keyboard, focus, queue, and resume
checks remain boundary tests. The isolated no-credential CLI subprocess took 7.18s and remains
because the absence of inherited host credentials is the boundary under test. After-run profiling
also exposed CP1252 decoding of a UTF-8 `git diff` in `evals.evidence.git_value`; a Windows regression
with U+201D reproduced the lost working-tree digest and background reader warning. The subprocess now
decodes UTF-8 explicitly.

Measured optimization choices for this cycle:

- Keep all four direct/module help invocations; defer evaluation/release imports until after
  `argparse` handles help, and block those imports in the subprocess regression.
- Run all removed aliases and options through the in-process CLI parser helper, retaining one
  external `python -m skail.cli.main` subprocess for the removed-alias exit contract; the installed
  console script remains covered by `tests/contract/test_cli.py`.
- Compare the same parallel fixture under `auto` and `serial`, assert the captured workspace files
  match, and keep observed peak concurrency at three versus one. Economy and quality remain in the
  paired-matrix suite.
- Build/install/inspect one release wheel and sdist in `package_check.py` before release-suite tests;
  pass that actual wheel through `SKAIL_PACKAGE_ARTIFACT_DIR` to `test_packaging.py` and
  `--artifact-dir` to `release_check.py`. Local and fast-PR runs still build a real wheel.
- The mounted TUI profile found no pure formatting test that still needed a mounted app; keyboard,
  focus, question, queue, resume, onboarding, and responsive-layout pilots remain mounted.
- Removed the smaller two-step Shift-Tab pilot because the existing five-step pilot covers the same
  entry path, all tabs, and retained composer focus in one mounted app.
- A trial merge of the discovered-model rejection and manual model-selection pilots took 4.27s,
  versus a 3.96s median for the separate baseline cases. They remain separate because they exercise
  distinct catalog and manual-selection paths.
- Tab cycling and `/plan`, `/budget`, and `/agents` navigation now share one mounted keyboard pilot;
  it still checks all five focus-preserving Shift-Tab transitions.

The final offline suite passed 1,185 tests with 5 skips on each of three serial runs. Wall times were
169.45s, 166.24s, and 166.71s (166.71s median); pytest-reported times were 165.70s, 161.75s, and
163.01s (163.01s median). The wall median is 1.5% longer than the 164.17s baseline median, so the
requested 20% suite reduction was not met; the suite adds nine passing regressions. Final reports are
`out/live-agentic/offline-post-package-path-{1,2,3}.txt`. The measured bottleneck tests improved:
direct/module help fell from 15.84s to 0.62s, removed aliases from 8.96s to 0.87s plus an in-process
check, the parallel evaluation fixture from 5.09s to a 3.25s median, and real-wheel inspection from
6.02s to a 5.10s median. The isolated no-credential subprocess fell from 7.18s to a 3.95s median.
The mounted TUI slice stayed near baseline (64.31s after versus 64.11s before). The final warnings
match baseline; explicit UTF-8 decoding eliminated the after-run CP1252 reader warning. More
TUI/subprocess consolidation would remove independent boundaries, so the timing target remains
unmet rather than weakening those checks.

## Defect crosswalk against latest exports

Reconciled every registry entry against the latest applicable export across the historical schema-v2
sessions and the DevPass retest session (the main campaign export was updated at 2026-09-24
22:34:47 UTC). Detailed run/task/attempt/call evidence remains in `out/live-agentic/BUGS.md` and
`OUTPUT_MISFORMATS.md`. The DevPass catalog and S1/S2 retests are reconciled. S3 first hit a
zero-call config-revision failure, then passed with Qwen and GPT-4.1 after commit `b278324`. The
final export still shows that historical parent run as `running`; future pre-assignment failures
now terminalize in `84f798d`. S4 later ran through a TTY but failed child-result acceptance;
S6 later reproduced the stale-selection completion and needs a post-fix TTY retest. S5 remains
withheld because its historical cause is unknown.

| Entry | Latest evidence classification |
|---|---|
| LIVE-001 | Current catalog availability confirmed through Skail: 142/142 priced; paid S1 GPT-4.1 assignment and S3 Qwen/GPT-4.1 assignments confirmed against the frozen selected-model rates. |
| LIVE-002 | Direct S2 admitted no plan or child; normalization implementation failure is tracked under LIVE-033. |
| LIVE-003 | Fixed offline; provider-call cancellation rendering pending. |
| LIVE-004 | Fixed offline; live queue-shutdown warning check pending. |
| LIVE-005 | 32-call ceiling confirmed live in S6; repeated-call arguments are absent, so identical-call cause is unknown. |
| LIVE-006 | Run-scoped checkpoint fix verified offline; live unrelated-run/plan check pending; restart queue persistence unproven. |
| LIVE-007 | Expected question interrupt confirmed in S6; separate S4 display check pending. |
| LIVE-008 | Fixed and confirmed live on resume. |
| LIVE-009 | Closed as a direct-mode verification plan mismatch. |
| LIVE-010 | Fixed and confirmed live in an 80×24 TUI. |
| LIVE-011 | UTF-8 fix confirmed live in S3. |
| LIVE-012 | Direct/no-delegate conflict rejection confirmed live in S3. |
| LIVE-013 | Exact-count rejection confirmed live; successful two-writer result remains incomplete. |
| LIVE-014 | Fixed offline; a matching live blocked-plan transition remains pending. |
| LIVE-015 | Closed as a test-plan mismatch; operator integration test remains pending. |
| LIVE-016 | Named implementer plans were admitted live, but S4 child results failed validation and the checkpoint did not complete; a scope enforcement fix is in `d92b4b9`, with direct denied-write live evidence pending. |
| LIVE-017 | Fixed offline; live cancellation had no child, so active-child cleanup remains unconfirmed. |
| LIVE-018 | Fixed offline; the old empty headless invocation remains evidence, fresh live CLI recheck pending. |
| LIVE-019 | Plan dispatch without duplicate `task()` confirmed live; FIFO completion remains pending. |
| LIVE-020 | Fixed offline; later GLM assignments support the reservation diagnosis, full S4 remains incomplete. |
| LIVE-021 | Provider call outcome unknown; locally settled; do not replay. |
| LIVE-022 | Provider call outcome unknown; locally settled; do not replay. |
| LIVE-023 | Closed as expected session-history projection. |
| LIVE-024 | Open: three S5 explorer runs produced no accepted results; offline handoff diagnostics now include `validation_path` for future failures; historical S5 cause remains unknown; no additional attempt. |
| LIVE-025 | Ambiguous provider call locally settled; outcome unknown; do not replay. |
| LIVE-026 | Resource-scope guidance fixed offline; S4 exposed that `PlanNode.resource_scopes` were not reaching the filesystem backend. Commit `d92b4b9` maps the declared scopes into child write permissions; live recheck pending. The invalid field in run 9c251 remains unknown. |
| LIVE-027 | Fixed offline; a later planned run admitted and blocked truthfully, but rejected/no-decision live edge remains pending. |
| LIVE-028 | Top-level planned mode with “do not delegate further” admitted live; nested child delegation was not exercised. |
| LIVE-029 | Question display, restoration, and accepted `JSON` answer confirmed live; work continuation is LIVE-030. |
| LIVE-030 | The same-run S6 retest confirmed another stale waiting prefix; `7b54772` blocks it offline, and a new same-run live check is pending. |
| LIVE-031 | Fixed and rechecked live. |
| LIVE-032 | Fixed and rechecked live. |
| LIVE-033 | Initial S2 implementation dropped existing lowercasing; operator test failed 2/4. Same-session correction restored lowercasing and scoped the test; operator focused test passed 4/4. Six-call local ledger reconciled; TUI/export match not observed. |
| LIVE-034 | S3 zero-call config-revision failure reproduced offline and fixed in `b278324`; the live Economy-mode retry routed both pinned models successfully. Final answer TUI/export text comparison was not captured. |
| LIVE-035 | The first S3 run has no assignment or provider call; its task/attempt are interrupted, but the parent run remains `running` in the final export. Future pre-assignment exceptions now terminalize through `84f798d`; historical state is preserved. |
| LIVE-036 | S4 child TaskResult responses failed across repeated plans, including the previously unlogged run `be73b1cc-6df8-43a0-8d38-3e8d8da76bc6` (16 calls, USD 0.019030400). The latest Qwen run had parser `$.artifacts.0.kind` and report `$` failures. No child result reached the checkpoint; S4 remains failed. |
| LIVE-037 | An earlier S4 report child wrote `src/live_fixture/report_test.py` outside its declared scopes. The red/green filesystem boundary fix is in `d92b4b9`; later report worktrees contain no such file, but no direct post-fix denied-write event was observed. |
| LIVE-038 | S6 accepted `JSON` in run `5a216e69-9126-49b0-849f-9811d5ba0a35` and then completed with a stale “Awaiting your selection” result. `7b54772` blocks that variant offline; same-run live recheck pending. |
| OUT-001 | Fixed offline; live provider-cancellation rendering pending. |
| OUT-002 | Answer-only presentation confirmed live in S1; historical raw model response remains unavailable. |
| OUT-003 | Fixed offline; live unawaited-coroutine check pending. |
| OUT-004 | Expected question interrupt confirmed in S6; S4 card display pending. |
| OUT-005 | Question Answer/Cancel card confirmed live; separate permission card remains unobserved. |
| OUT-006 | Original model-authored options mismatch confirmed; tool guidance fixed offline, matching live question pending. |
| OUT-007 | Fixed and confirmed live at 80×24. |
| OUT-008 | UTF-8 handling confirmed live in S3. |
| OUT-009 | Resource-scope guidance fixed offline and plans were admitted, but S4 exposed an out-of-scope child write in its isolated worktree; `d92b4b9` carries scopes to the filesystem boundary, live recheck pending. |
| OUT-010 | False successes fixed offline; latest planned run blocked truthfully, invalid/no-plan live path pending. |
| OUT-011 | Question interrupt and restored card confirmed live. |
| OUT-012 | Fixed offline to block stale waiting completion; same-run live recheck pending. |
| OUT-013 | S4 child TaskResult outputs failed at `$.status`, `$.artifacts.0`, `$.verification.0.evidence_ref`, and finally `$.artifacts.0.kind` / `$`; no accepted results. |
| OUT-014 | S6 stale “Awaiting your selection” completion is fixed offline in `7b54772`; same-run live recheck pending. |

## Next execution cycle

- [x] 10. Reconcile LIVE-001–032 and OUT-001–012 against the latest exports; correct stale
  statuses, link each open item to a reproducer, and preserve uncertain call outcomes.
- [ ] 11. Diagnose S5 explorer result failures (LIVE-024) with safe failure-category evidence,
  then prove accepted child results, checkpoint, and revision in deterministic tests. Historical
  exports lack child results and failure categories, so their exact cause remains unknown; S5 is
  withheld and no additional attempt has been made.
  - The 2026-09-26 review of `session-S5-final-retry-final.json` (run
    `071ba5b0-5c91-479d-bb14-74db2e951997`) found `task.failed` with null reason, no
    `failure_category`, no `validation_path`, and no raw child result. Offline evidence still cannot
    establish the cause; S5 stays withheld, with no paid retry. The accepted-result, checkpoint, and
    revision criteria remain incomplete.
- [x] 12. Reproduce and repair same-run post-answer continuation (LIVE-030/OUT-012); inspect
  the repeated S6 tool sequence before changing loop detection. The schema-v2 export for run
  `5a216e69-9126-49b0-849f-9811d5ba0a35` records one failed `execution_decision`, one `ask_user`,
  an accepted `user.answer` (`JSON`), then `run.completed` with the stale “Awaiting your
  selection...” blocked summary. The existing guard recognized only “Waiting for your answer”.
  A regression for this exact alternate prefix failed before the fix and passes after extending
  the guard. Tool-name evidence has no repeated identical-call sequence; no loop-detector change.
  A later same-run live retest in run `e12b7b3e-e2a9-402a-a0bb-8e9e34c14c96` accepted `JSON`
  and then completed with output status `waiting_for_user`, stale “A blocking question was asked...”
  summary, and no file changes. A third regression for the structured status failed before the
  guard was extended and passes after it. This live run is an S6 failure; post-fix live confirmation
  remains pending. A second post-fix run `b4235f5b-0c92-419b-9803-adbc4f00c8ff` also accepted
  `JSON`, then emitted `run.completed` with output status `blocked`, a stale waiting summary, and
  no changed paths. The structured summary path now has a failing/green regression and guard. S6
  still fails because no selected-format implementation or focused test exists; do not repeat
  without a distinct corrective route.
- [x] 13. Recheck prior intent, ownership, queue, cancellation, question, output, and UTF-8
  fixes with focused regressions. Live-pending closures remain tied to matching live observations.
- [x] 14. Baseline the offline suite three times, map independent mechanisms, optimize measured
  bottlenecks, and report the measured result. The 20% target was missed; boundary tests were kept.
- [x] 15. Review overlapping CI gates and harmonize Ruff paths without reducing supported
  Python/platform checks.
- [x] 16. Pass Ruff, mypy, unit/contract, smoke, and full offline suite in repository order;
  record final counts and before/after timings after the package path fix.
- [ ] 17. Refresh the disposable fixture and live plan; freeze models/prices and a new
  in-house subledger under the cumulative stop; S1–S3 are rechecked, S4 remains failed after
  bounded plans, S6 remains incomplete after two same-run post-fix attempts, S5 is withheld, S7 is
  unchanged, and S8 has been exercised under its natural-failure rule but failed at result
  validation/retry eligibility. S6 used USD 0.165876 of its USD 0.75 allocation, leaving
  USD 0.584124; S8 used USD 0.024644374 of its USD 1.50 allocation. Reconcile after every call and
  update all evidence.
- [x] Reconcile the latest complete retest export before more paid calls. The earlier USD
  0.002510000 gap was the third S6 call. A second audit found 16 omitted S4 calls costing USD
  0.019030400. At the prior checkpoint, all 213 retest call IDs were audited once for USD
  0.354409976. Two S6 exports add six calls totaling USD 0.023594000 and S8 adds 25 calls totaling
  USD 0.024644374; all 244 retest IDs now match `CALL_COST_AUDIT.csv` once and match exported
  `model_usage`. `COSTS.csv` cumulative local cost is USD 2.997053084; headroom is USD 5.502946916
  to the USD 8.50 normal stop and USD 7.002946916 to the USD 10 ceiling. Provider billing remains
  unknown. The two malformed zero-cost CSV placeholders were corrected without removing any
  paid-call evidence.
- [x] Verify a bidirectional terminal path. A `cmd.exe /k` PTY in this environment reported
  Python `stdin.isatty() == True` and `stdout.isatty() == True`. The earlier `True False` result
  remains evidence for its separate shell invocation. No Skail TUI or provider call was launched
  during this verification; recheck from the isolated fixture before S6.
- [x] 18. Audit README, specs, ADRs, and test procedures against verified behavior; check
  local links and commands; commit coherent changes with Conventional Commit messages.
  - Checked architecture, features, the plan, checklist, live plan, and local links in docs/skail,
    docs/decisions, and tasks. The README audit was read-only; 53 local links resolve and the
    documented CLI, lint, benchmark, eval, smoke, package, release, and uninstall commands were
    checked. No verified README inaccuracy was found, so README remains unchanged. The public
    v0.1.0 release endpoint returned 404, consistent with the Unreleased badge. The verified
    behavior and documentation changes are committed with Conventional Commit messages.
- [ ] 19. Re-profile and safely condense the current full offline suite. The latest three serial
  runs collected 1,200 cases each (1,195 passed, 5 skipped), with pytest-reported times 109.25s,
  109.15s, and 111.52s (109.25s median). This is 33.5% below the 164.17s original baseline
  median, but 52.02s below the preceding 161.27s median on the same platform and command despite
  one additional test and no suite-performance change. That unexplained variance prevents a
  repeatable gain claim; keep the objective open and investigate it before closing the 20% target.
  Preserve both series at `offline-final-e9fdf6b-s6guard-durations-{1,2,3}-python-pytest.txt`
  and `offline-final-e9fdf6b-s6guard2-durations-{1,2,3}-python-pytest.txt`.
  Final ordered gates passed: Ruff, mypy (126 files), unit/contract (903 passed, 2 skipped),
  smoke, and full suite (1,195 passed, 5 skipped); the focused stale-result regression passed 4.
- [x] 20a. Complete the offline S4 export diagnosis and attempt-two handoff regression. The
  2026-09-26 review of `session-S4-qwen-final.json` (run
  `9652cfc8-bd46-4195-81e8-1419efd41ef1`) records parser task
  `19f3f5d0-fe75-48e6-a0f7-4063ab40a832` rejected with `result_validation` at
  `$.artifacts.0.kind`, and report task `9aecab0e-3e19-430d-8823-cc91834e59f8` rejected as
  `malformed_result` at `$`; raw child output is absent. These observations match invalid-output
  rejection, not proof of schema-valid TaskResult rejection. Existing contract tests accept valid
  artifact `kind`/`path` and verification evidence for the fields they cover; the live export has
  no valid result that was dropped. The operator prompt named artifact shapes, but the runtime
  child contract does not specify `{kind, path, digest}`; this is a guidance gap consistent with
  the validation path, not an established cause of model output. Attempt-two handoff now carries
  allowlisted `failure_category` and schema-shaped `validation_path`, dropping unknown categories
  and unsafe paths without raw output. Its regression and focused tests pass (9 passed); Ruff and
  mypy passed on this revision.
- [ ] 20b. Before another paid S4 attempt, separately justify a fresh fixture run and establish
  the acceptance repair or eligible route. The acceptance bug was not reproduced offline, and the
  handoff change does not make S4 live-eligible. S4 remains failed live; direct post-fix denied-write
  observation is pending (`d92b4b9` remains the offline denied-write repair). Two accepted
  implementer results, checkpoint, disjoint scopes, and FIFO follow-up are still required. Record
  the formerly omitted run `be73b1cc-6df8-43a0-8d38-3e8d8da76bc6` under LIVE-036/OUT-013. Maintain
   S5's separate eligibility gate because its historical cause remains unknown.

## 2026-09-26 handoff revision and audit update

- Handoff commit `e7f2ba535cc6d62271c13db2914c385e332176af` passed Ruff, mypy, unit/contract
  (901 passed, 2 skipped), smoke, and full suite (1,191 passed, 4 skipped, 1 deselected).
  Collection comparison reported 1,195/1,196 collected, 1 deselected. Its single full-suite gate
  took 109.38s wall / 106.58s pytest time; this does not replace the three-run median.
- Earlier suite speed profile: no safe candidate was retained; objective remained open. Its
  comparable median was 166.71s vs baseline 164.17s. Preserve wheel, subprocess, evaluation,
  security, and mounted TUI boundaries. Slowest test in that revision was
  `tests/unit/test_packaging.py::test_wheel_contains_only_the_skail_runtime` (4.54s).
- Final revision profile after the S6 recovery regressions and `waiting_for_user` guard: 1,194
  passed, 5 skipped in each of three runs. Wall median 161.27s; pytest median 157.70s. The observed
  medians are slightly below baseline, but sample ranges overlap and no speed gain is attributed to
  code changes. The 20% target remains unmet; no boundary-preserving consolidation remains.
- S6 retest was blocked before launch because the agent command runner is not a bidirectional PTY
  (`stdout.isatty() == False`). Earlier `cmd.exe /k` `True/True` result remains valid for a
  different PTY. No paid call; item 17 stays unchecked. Do not authorize a headless substitute.
- S4 paid retry remains unjustified; S5 remains withheld. Item 9 stays unchecked.
- Item 18 README/documentation audit is complete. README was checked read-only with no verified
  inaccuracy; local links and documented commands were verified.
