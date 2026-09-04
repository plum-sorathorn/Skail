# Rudder v0.1.0 Release Remediation Plan

Status: **In progress — release sign-off withheld**

This is the authoritative execution tracker for the Phase 6–8 audit remediation. It supplements
the historical implementation plan; it does not change the accepted product invariants, ADRs, or
the requirement that `legacy/autoconduck/` remain inert.

## Release decision

- [x] Invalidate the prior v0.1.0 release-candidate evidence.
- [x] Keep the v0.1.0 target as a new release candidate, not a v0.1.1 patch.
- [x] Require offline deterministic end-to-end evidence; live-provider validation stays opt-in.
- [x] Keep the TUI in stable v0.1.0 scope rather than deferring it.
- [ ] Create the fresh v0.1.0 release candidate and annotated release tag.

## 1. Authoritative runtime lifecycle

- [x] Persist lead context packets before a lead model call.
- [x] Persist terminal lead run, task, attempt, and session status on normal completion and failure.
  - Implemented in `be71cdf`.
- [x] Persist child context packets, translate child execution exceptions into structured failures,
  and remove fabricated required-verification evidence.
  - Implemented in `823518c`.
- [x] Route every lead and child assignment through `AssignmentService` and `BudgetLedger`.
  - Implemented in `f66ff52`.
- [x] Require a reservation before every provider call; settle actual usage or reclaim reservations
  on failure, cancellation, and recovery.
  - Implemented in `f66ff52`.
- [x] Bind every healthy attempt through `PersistedAssignmentRegistry` and
  `TaskBoundModelMiddleware` before its first call.
  - Implemented in `f66ff52`.
- [x] Register live delegated tasks with `TaskRegistry` and dispatch through `ChildScheduler` so
  dependency order, cycle rejection, priority, the three-child limit, and writer leases apply to
  model `task` calls.
  - Implemented in `f66ff52`.
- [x] Implement production escalation using a distinct eligible model, failed-model exclusion, and
  the +0.15 floor; the second failure must return once to the lead.
  - Implemented in `f66ff52`.
- [x] Replace all remaining success inference with evidence-bearing verification results.
  - Implemented in `f66ff52`.

## 2. Context, secrets, recovery, and projection

- [x] Enforce compaction token budgets, record omissions, and persist compaction packets without
  rewriting usage records.
  - Implemented in `0c56a8c`.
- [x] Make `TuiProjection.apply_snapshot()` reconstruct state idempotently.
  - Implemented in `403da8c`.
- [x] Inject one run-scoped redaction registry into credentials, controller, journal, tool output,
  exception handling, context packets, checkpoints, and exports.
  - Implemented in `1abe230`.
- [x] Add resolved-credential canary tests proving no secret reaches those persisted or displayed
  surfaces.
  - Implemented in `1abe230`.
- [x] Write real checkpoint metadata at resumable lifecycle boundaries and make normal session
  resume restore terminal, interrupted, and approval-waiting runs.
  - Implemented in `1abe230`.
- [x] Persist task/attempt transitions transactionally with assignment and budget changes.
  - Implemented in `1abe230`.

## 3. CLI and TUI integration

- [x] Resolve configured provider/catalog models in normal CLI execution; retain fake models only
  for explicit test, smoke, and evaluation modes.
- [x] Use one real run ID across CLI, journal, checkpoints, `RunResult`, print output, and JSONL.
- [x] Stream redacted persisted runtime events in JSONL, followed by one correlated terminal event.
- [x] Derive documented success, failed, blocked/approval-required, cancelled, and usage exit codes
  from terminal runtime state.
- [x] Make non-interactive approval requirements fail fast.
- [x] Bind TUI submit, approval/rejection, cancellation, resume, compaction, and supported
  foreground steering to `RunController`, `SessionService`, and `ApprovalStore`.
- [x] Standardize the streaming CLI flag as `--jsonl`; retain `--json` only as a documented
  compatibility alias if needed.

## 4. Evaluation and release evidence

- [x] Remove evaluator-side oracle mutation and artificial parallel timing; fixture changes now
  pass through Rudder's runtime tool boundary.
  - Implemented in `2d5b389`.
- [x] Regenerate and validate fresh evaluation evidence in `release_check.py` rather than accepting
  a stale result file.
  - Implemented in `db29f1e`.
- [ ] Make `auto`, `economy`, `quality`, `serial`, and `no_delegation` drive concrete runtime
  controls and collect assignments, budgets, events, and timing from the journal.
- [ ] Build genuine parallel fixture workloads; do not claim speedup until they demonstrate it.
- [ ] Make evaluator `seed`, `base_workspace`, and provider mode functional, or remove unsupported
  public options.
- [ ] Require release checks to validate all fixtures, policies, report schema, freshness, and all
  acceptance gates.

## 5. Documentation and release closeout

- [ ] Update `tasks/plan.md` and `tasks/todo.md` to show the reopened Phase 6–8/final-checkpoint
  work accurately.
- [ ] Synchronize `AGENTS.md`, README, `docs/`, package metadata, repository URLs, CLI syntax,
  exit codes, support levels, security claims, and measured benchmark values with shipped code.
- [ ] Record benchmark environment/date and regenerate baselines.
- [ ] Run `graphify update .`, `rtk pytest`, security and contract suites, mypy, Ruff, benchmarks,
  wheel inspection, and the strengthened release check.
- [ ] Review a clean complete diff and commit documentation as
  `docs(rudder): synchronize all documentation and repository metadata for v0.1.0 release`.
- [ ] Tag the verified release as `v0.1.0`; only then update the GitHub repository name/remote.

## Current verification

- [x] Focused lifecycle, task-graph, compaction, projection, and evaluator tests passed after their
  respective remediation commits.
- [x] Focused mypy, Ruff, and diff checks passed for every completed slice.
- [x] Knowledge graph refreshed after the implementation slices.
- [ ] Full release verification passes. It is expected to fail until the unchecked runtime, CLI/TUI,
  checkpoint, and real-policy-evaluation work above is complete.

## Completed remediation commits

| Commit | Completed work |
|---|---|
| `be71cdf` | Lead terminal lifecycle and context persistence |
| `0c56a8c` | Bounded, persisted compaction |
| `823518c` | Child failures, child context persistence, non-fabricated verification |
| `403da8c` | Idempotent TUI projection reconstruction |
| `2d5b389` | Runtime-tool-backed fixture execution and honest timing |
| `db29f1e` | Fresh evaluation validation in the release gate |
| `f66ff52` | Authoritative runtime lifecycle, task graph scheduling, and model bound execution |
| `1abe230` | Run-scoped redaction registry, transactional status updates, and checkpoint recovery |
