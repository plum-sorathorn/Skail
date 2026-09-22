# Phase 21 Final Integrated Review

Status: Complete
Date: 2026-09-14
Reviewed baseline: `0b78744`
Reviewed input: `b496d96f46f412223fe844b30ed74f7cdd53236a`

## Scope and method

This fresh review covers the complete adaptive-runtime change since the guide's starting baseline.
It applies ADR 0006, the active specification and architecture contracts, the feature contracts,
and the Phase 21 acceptance criteria. The review used the complete commit and path inventory, then
examined the highest-risk implementation and evidence boundaries: real CLI/TUI entry paths,
security, journal migrations and recovery, model and plan identity, budget ownership, isolated
workspace integration, release recomputation, packaging, and documentation truth.

Earlier phase handoffs and the Phase 16 review were used to locate evidence, but later behavior was
rechecked against the current input. Synthetic fixtures were used only as deterministic engineering
evidence. No live-provider run, paid call, push, publication, tag, remote change, or legacy cleanup
was performed.

## Findings and disposition

No unresolved critical or high finding remains.

1. **High — closed: the integrated release verifier rejected the canonical package.** The
   Phase 20a rename changed the old-package rejection predicate in
   `scripts/release_check.py::check_wheel_contents()` into a predicate that rejected every
   `skail/` member. The release workflow therefore could not pass even when the separately invoked
   package checker succeeded. The integrated verifier now calls the canonical
   `scripts.package_check.inspect_wheel()` policy, and a regression constructs a canonical wheel
   and exercises the integrated gate. A real local build then verified 110 runtime package files
   with no development or legacy content.
2. **Medium — closed: active transition documents described Skail as replacing itself.** Mechanical
   rename text said that Skail succeeded or replaced Skail, that a wheel must contain and not
   contain `skail`, and that the active import boundary rejected `skail`. The active index,
   specification, migration contract, feature table, and founding ADR now distinguish Skail from
   the archived predecessor without restoring a former public identity. Documentation contracts
   reject the contradictory forms.

No other correctness, security, architecture, performance, or documentation issue found in this
review reaches critical/high severity or blocks Phase 22. Exact-candidate platform evidence remains
a later release prerequisite, not a finding waived by this review.

## Representative end-to-end traces

All traces use deterministic local fixtures and persisted runtime state.

| Trace | Executed evidence | Observed contract |
| --- | --- | --- |
| Direct execution | `test_headless_core_direct_execution_path` | A typed direct decision performs the workspace write, returns the lead result, and creates no child result. |
| Discovery and replan | `test_discovery_checkpoint_wakes_lead_and_dispatches_revision` | Discovery evidence wakes the lead, admits revision 2, and completes the revised dependency graph. |
| Isolated parallel integration | `test_disjoint_worktree_writers_overlap_before_serial_integration` | Disjoint worktree writers overlap, while captured changesets enter the canonical workspace through serialized integration. |
| Approval and resume | `test_approval_interrupt_resume_runs_approved_command_once` | A persisted direct command blocks for approval, resumes after exact `ALLOW_ONCE`, performs one effect, and consumes the grant. |
| Budget block | `test_task_graph_keeps_budget_block_distinct_and_never_executes` | An unaffordable assignment returns `budget_blocked` and never invokes the executor. |
| Cancellation | `test_cancelling_planned_work_marks_inflight_nodes_terminal` | Cancellation persists cancelled in-flight nodes, blocks their dependent, and records the run and lead task terminal states. |

The same trace run also exercised a real CLI JSONL invocation and the TUI command-approval resume
path. The CLI retained versioned terminal framing, and the TUI executed the approved command once.

## Review domains

| Domain | Reviewed implementation and evidence | Disposition |
| --- | --- | --- |
| CLI/TUI | CLI runtime bootstrap and `_execute_instruction`; `SkailApp`, projection, session, resume, JSONL, exit-code, and approval tests | Real fake-provider CLI and mounted TUI/controller paths pass; claims remain bounded to those paths. |
| Security | Filesystem/link boundaries, command policy, trust, approval scoping, redaction canaries, recovery, and worktree ownership | The affected security/contract matrix passes with one fail-closed local link-capability skip. |
| Migrations and recovery | Ordered journal migrations, idempotent schema creation, checkpoint separation, interrupted attempts, ambiguous calls, reservations, and plan executions | Prior records are preserved; ambiguous paid/effectful work is not replayed. |
| Model and plan contracts | Execution decisions, plan validation/revision, task compatibility admission, assignment persistence, model stickiness, and two-attempt escalation | Typed identities and hard requirements remain bound across direct, planned, compatibility, and resumed work. |
| Budget ownership | `AssignmentService`, `BudgetLedger`, `AssignmentUsageSettler`, lead continuation allowances, fallback release, and failure reconciliation | Reservations precede calls; failed or unknown settlement blocks unsafe paid execution. |
| Workspace integration | Snapshot capture, declared scope, immutable images, worktree ownership, serialized apply, conflicts, and in-doubt recovery | Concurrent writers do not overlap canonical writes; uncertain apply is not replayed. |
| Release recomputation | Raw invocation coverage, oracle replay, provenance/digests, numeric domains, expected failures, summaries, comparisons, and synthetic qualification boundary | Serialized summaries and `all_gates_passed` cannot forge eligibility. |
| Packaging and documentation | Wheel/sdist inspection, isolated installed command, CI matrix, active README/contracts, evidence limits, and product identity | Canonical package gate and documentation contradictions are closed; exact-candidate platform execution remains Phase 22/24 evidence. |

## Historical remediation 7–9 ownership

| Historical requirement | Active implementation/test owner | Phase 21 disposition |
| --- | --- | --- |
| Remediation 7 — post-commit correlated journal, JSONL, and TUI events | Phases 02–03; event bus, event envelope, CLI E2E, projection, and recovery tests | Implemented and revalidated. |
| Remediation 7 — terminal stdout, compatibility flags, exit codes, and isolated CLI state | Phase 03; CLI contract and E2E tests | Implemented and revalidated. |
| Remediation 8 — scripted execution independent from oracle expectations and route estimates | Phases 04–05; fixture-contract, evaluator, and evidence tests | Implemented and revalidated. |
| Remediation 8 — equivalent useful serial/parallel work, overlap, settlement, paired repetitions, and retained failures | Phases 11–12 and 15; worktree overlap and paired matrix/profile/statistics tests | Implemented for deterministic engineering evidence and revalidated. |
| Remediation 8 — preserve the 15% end-to-end timing gate without manipulating fixtures | Phases 15–17; frozen paired-runtime profile, comparison, and release-check tests | Implemented and revalidated; it is not live-provider evidence. |
| Remediation 9 — independently recompute summaries and reject forged or incomplete reports | Phase 17; `validate_eval_report` adversarial tests | Implemented and revalidated. Summary fields cannot confer tag eligibility. |
| Remediation 9 — isolated wheel/sdist installation and exact-candidate Windows/Linux evidence | Phase 18 plus Phases 22 and 24; package checker, packaging tests, and release workflow | Local mechanics are implemented; exact final-candidate platform evidence remains explicitly owned by Phases 22 and 24. |
| Remediation 9 — synchronize active documentation after verified implementation | Phase 20 plus Phase 23; documentation contracts and final synchronization gate | Current claims are reconciled; Phase 23 still owns the frozen final documentation commit. |

Every historical remediation 7–9 bullet therefore has an implementation and test/evidence owner in
the active guide. The remaining exact-candidate work is dependency-ordered rather than missing.

## Verification record

- Representative runtime/CLI/TUI traces: 8 passed.
- Release recomputation and packaging regressions: 23 passed.
- Integrated review matrix: 324 passed, 1 skipped.
- Event/evaluation/timing ownership matrix: 82 passed.
- Real integrated wheel inspection: 110 `skail/` package files, no forbidden content.
- Complete offline suite: 682 passed, 4 skipped.
- Ruff: passed across `src`, `tests`, `scripts`, `evals`, and `benchmarks`.
- Strict mypy: passed for all 110 `src/skail` source files.
- Fake-provider smoke: passed.
- Isolated wheel/sdist build, inspection, installed-command, and smoke verification: passed on the
  reviewed input commit. Phase 22 must regenerate it for the committed Phase 21 candidate.

Graphify and final diff/staging checks are recorded in the Phase 21 handoff because they run after
this audit record is finalized.

## Remaining evidence boundary

Phase 21 does not certify the release or authorize a tag. Phase 22 must create a clean isolated
Windows candidate at the Phase 21 commit and regenerate all candidate-bound local evidence. Phase
24 still requires exact-final-commit Windows and Linux evidence before any separately authorized
tag. Live-provider quality parity, economic savings, and route promotion remain unproven until Q1.
