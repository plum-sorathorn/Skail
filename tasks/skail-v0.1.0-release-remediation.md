# Skail v0.1.0 Release Remediation Plan

Status: **Historical audit record — release sign-off remains withheld**

This is the historical audit-remediation tracker. Active work proceeds through the
[adaptive orchestration and release guide](skail-adaptive-orchestration-and-release-plan.md), which
preserves completed evidence here and maps every unfinished item to a numbered owner. This record
does not change the requirement that `legacy/skail/` remain inert.

## Active-guide mapping

| Historical item | Active owner |
|---|---|
| Phase 2 provider/configuration composition | Phase 01 revalidates the routing boundary; demonstrated defects remain repair prerequisites |
| Phase 7 persisted events and exit behavior | Phases 02–03 |
| Phase 8 independent evaluation and timing | Phases 04–05 and 15 |
| Phase 9 release checks, CI, and documentation | Phases 17–24 |
| Worktree isolation | Phases 11–12 |
| Economic savings qualification | Q1, separately authorized |
| Legacy cleanup | C1, separately authorized |

The release tag in phase 24 requires separate explicit authorization and exact-commit platform
evidence. Creating a tag never authorizes a repository or remote rename.

## Historical remediation phases

Each phase required a separate, reviewable commit under this tracker. Historical checkmarks below
record partial implementation work only; open release claims are now owned by the active-guide
mapping above.

### Phase 1 — Accurate tracker and preserved evidence

- [x] Reconcile the audit with the current worktree; link this tracker from the historical plan and
  delivery checklist.
- [x] Withdraw unsupported evaluation and release claims, retain the 450 ms seed diagnostics, and
  label existing `evals/results/` reports invalid for release sign-off.
- [x] Remove the unverified 650 ms timing adjustment and restore the 100 appends/sec benchmark
  threshold with a regression test.

Evidence: `docs/skail/EVALUATION.md`, `docs/skail/PERFORMANCE.md`,
`tests/unit/test_bench_runner.py`, and the phase commit. The untracked `out/` diagnostic material
is preserved outside the commit.

### Phase 2 — Provider and configuration composition

- [ ] Build one typed CLI/TUI runtime bootstrap result for effective configuration, adapters,
  qualified model identities, catalog, permissions, redaction, and controls.
- [ ] Enforce catalog-backed production routing, explicit fake execution, provider-qualified model
  pins, trusted configuration loading, supported adapter construction, and manual-only unknowns.
- [ ] Represent unknown cost explicitly and make inspection reflect execution state.

Acceptance evidence: configuration/provider contract regressions and CLI/TUI inspection tests.

### Phase 3 — Authoritative provider-call accounting

- [x] Persist call identities and reservations before every call; distinguish replay from new work.
- [x] Normalize framework usage, settle once, fund calls from batch allowances without double
  reservation, and retain authoritative, estimated, and unknown charges separately.
- [x] Block paid execution on uncertain reconciliation and preserve existing journals through
  migration coverage.

Acceptance evidence: `tests/integration/test_assignment.py`, `tests/unit/test_journal.py`, the
affected 78-test runtime/recovery matrix, and the complete offline suite. Provider calls use the
persisted assignment reservation as their funding allowance; no second reservation is created.

### Phase 4 — Delegated task contracts and scheduling

- [x] Preserve the standard task surface while validating full JSON packets, durable dependency
  identities, duplicate fingerprints, profiles, scope, and budgets.
- [x] Dispatch by the scheduler queue and priority; release dependencies only after verification.
- [x] Persist terminal task results and two-attempt escalation evidence; preserve writer leases
  through cancellation and shell shutdown.

Acceptance evidence: task validation/registry, ordered scheduler concurrency, compiled task graph,
two-attempt escalation, persisted terminal results, scoped filesystem, and cancellation-held lease
regressions. The complete offline suite passes with 489 tests and two documented skips.

### Phase 5 — Verifiable outcomes and failure monitoring

- [x] Require recorded executable evidence or bounded source-referenced analysis reports; reject
  malformed, empty, mismatched, and unsupported success results.
- [x] Preserve blocked/cancelled outcomes and correct repeated-error, progress, and configured-limit
  classification.

Acceptance evidence: task-result contract tests validate runtime file digests, source-bounded
model-authored analysis, malformed/empty/mismatched results, and unsupported evidence. Failure
monitor tests cover three repeated calls, distinct consecutive errors, normalized repeated errors,
successful progress, execution-status dictionaries, and configured call/time/budget limits. The
complete offline suite passes with 497 tests and two documented skips.

### Phase 6 — Recovery, approvals, redaction, and controls

- [x] Persist and restore original controls, workspace and lead identity, interrupts, task state,
  assignments, and allowance ownership.
- [x] Scope and atomically consume approvals; resume only the exact policy-rechecked command.
- [x] Reconcile lifecycle/checkpoint crashes, live redaction, same-session mutation, TUI commands,
  cancellation, and documented steering behavior.

Acceptance evidence: recovery tests restore the persisted control and workspace revision envelope;
approval tests prove atomic single-use consumption, exact action matching, and cross-session denial;
model-boundary canaries prove late-registered secrets are scrubbed in both directions. TUI coverage
exercises answer/resume, command approve/reject, explicit session selection, compaction, cancellation,
and the foreground worker lifecycle. The complete offline suite passes with 500 tests and two
documented skips.

### Phase 7 — Persisted events and exit behavior

- [x] Deliver post-commit correlated events to journal, JSONL, and TUI, including exactly one
  terminal event per invocation.
- [x] Preserve stdout, compatibility flags, exit codes, and isolated CLI test state.

Evidence: active-guide Phase 03a/03b commits `e78907f` and the Phase 03b commit; focused CLI,
event, controller, recovery, and TUI suites plus the full offline suite. Events carry one
invocation identity distinct from the resumable run identity; pre-persistence failures do not
fabricate terminal events.

Acceptance evidence: CLI/TUI/event-stream integration tests for every terminal outcome.

### Phase 8 — Independent evaluation and timing methodology

- [x] Separate scripted execution from oracle expectations and reported usage from routing estimates.
- [ ] Measure equivalent useful serial/parallel work with real overlap, full settlement, paired
  repetitions, fixed workloads, and retained raw failures.
- [ ] Keep the 15% end-to-end gate; optimise actual overhead if it fails rather than changing
  synthetic delay or thresholds.

Acceptance evidence: oracle-independence, workload-equivalence, overlap, and raw-metric tests.

### Phase 9 — Release checks, CI, and documentation

- [ ] Independently recompute release summaries from raw evidence; reject forged, stale, incomplete,
  mismatched, or insufficient reports.
- [ ] Validate fresh wheel/sdist installation outside the checkout and record Windows and Linux
  evidence for the exact candidate commit.
- [ ] Synchronize active documentation only after the verified implementation; retain diagnostic
  output outside the checkout.

Acceptance evidence: release-check regressions, packaging integration, platform CI evidence, and a
clean candidate commit. The requested documentation commit and `v0.1.0` tag occur only after this phase.

## Release decision

- [x] Invalidate the prior v0.1.0 release-candidate evidence.
- [x] Keep the v0.1.0 target as a new release candidate, not a v0.1.1 patch.
- [x] Require offline deterministic end-to-end evidence; live-provider validation stays opt-in.
- [x] Keep the TUI in stable v0.1.0 scope rather than deferring it.
- [ ] Create the fresh v0.1.0 release candidate and annotated release tag.

## Historical partial implementation inventory — not release acceptance

The following entries are preserved for auditability. Their checked state does not claim that the
full contract is complete; each is revalidated by the phase above that owns it.

### 1. Authoritative runtime lifecycle

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

### 2. Context, secrets, recovery, and projection

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

### 3. CLI and TUI integration

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

### 4. Evaluation and release evidence

- [x] Remove evaluator-side oracle mutation and artificial parallel timing; fixture changes now
  pass through Skail's runtime tool boundary.
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

### 5. Documentation and release closeout

- [ ] Update `tasks/plan.md` and `tasks/todo.md` to show the reopened Phase 6–8/final-checkpoint
  work accurately.
- [ ] Synchronize `AGENTS.md`, README, `docs/`, package metadata, repository URLs, CLI syntax,
  exit codes, support levels, security claims, and measured benchmark values with shipped code.
- [ ] Record benchmark environment/date and regenerate baselines.
- [ ] Run `graphify update .`, `rtk pytest`, security and contract suites, mypy, Ruff, benchmarks,
  wheel inspection, and the strengthened release check.
- [ ] Review a clean complete diff and commit documentation as
  `docs(skail): synchronize all documentation and repository metadata for v0.1.0 release`.
- [ ] Tag the verified release as `v0.1.0` only with separate explicit authorization; repository or
  remote renaming is a different external action and requires its own authorization.

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
