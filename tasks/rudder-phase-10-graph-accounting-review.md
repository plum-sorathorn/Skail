# Phase 10 adaptive graph and accounting review

Status: **Phase 10a audit complete; Phase 10 remains blocked by critical/high findings.**

Reviewed: 2026-09-07
Branch/commit: `rudder` at `7db893d`
Reviewer: Codex (current GPT-5 session; the plan's model assignment was treated as a recommendation)
Evidence class: local deterministic offline review; no live provider or external-service calls

## Scope and verdict

The review traced first-call assignment, reservation ownership, post-commit event delivery,
execution-decision enforcement, compatibility-task admission, persistent plan dispatch/recovery,
run and node cancellation, approval resume, stale revisions, and attempt lineage. Existing focused
tests cover cycle rejection, mixed planned/task bypass, stale revisions, exact-command approval
resume, and renamed-task lineage, but they do not cover the blocking coordinator exits below.

Verdict: **request changes**. Phase 10 cannot pass while a run can report completion without
executing accepted plan work, cancellation can leave a run and funded attempts live, or the offline
evaluator cannot execute its own mutation fixtures.

The code-review and doubt-driven workflows were applied. A fresh-context adversarial reviewer
received the Phase 10 contract and repository artifact without the primary reviewer's conclusions.
Each returned finding was rechecked against source or a deterministic production-path reproduction;
all ten were classified as valid and actionable. Cross-model CLI review was skipped because this
session did not authorize an external model invocation or provider spend.

## Blocking findings

### P10-001 — Critical — Discovery checkpoints never wake the lead

**Resolution:** fixed by Phase 10b on 2026-09-07. Production regressions now prove the same lead
assignment is woken, only available frontier evidence can authorize a typed revision, the journal
compare-and-set advances the plan, the checkpoint settles, and newly ready work dispatches. The
remaining Phase 10 findings are unchanged. Focused/affected verification passed 109 tests; the full
offline suite advanced from 578 to 580 passing tests and retained only the two previously recorded
evaluator failures and two Windows symlink skips.

**Production-path reproduction:** run a `RunController` with a discovery decision containing one
read-only agent followed by a checkpoint. The agent succeeds through the compiled child lifecycle.
The controller returns `completed`, the lead has made only its original two calls, and the persisted
plan is `{'inspect': 'succeeded', 'decide': 'ready'}`.

**Cause:** `_dispatch_admitted_plan_agents()` starts only `AGENT` and `TOOL` nodes. A ready
`CHECKPOINT` is ignored, and the empty-running-queue exit treats that state as completion. No
production path invokes `Journal.revise_plan()`.

**Affected invariant:** discovery must wake the lead at an evidence checkpoint; accepted plans may
finish only after their required checkpoints and revisions are resolved.

**Minimal repair:** make ready checkpoints a durable lead-wake boundary, expose evidence-bearing
revision admission through the controller, and refuse terminal run completion while an active plan
has ready/waiting/launching/running checkpoint work. Add a production `RunController` regression.

### P10-002 — Critical — A plan admitted after interrupt resume is never dispatched

**Resolution:** fixed by Phase 10c on 2026-09-08. Initial and resumed completion share one
finalization path that dispatches admitted plan work before terminal state, persisted safe
`READY` work is reconstructed on recovery with per-node re-admission, ambiguous
LAUNCHING/RUNNING nodes are held as BLOCKED rather than replayed, and lead assignment is
preserved across interrupt/resume. Production regressions prove question-interrupt resume
dispatches the plan once, recovery dispatches persisted READY work (including independent
READY work beside a bound sibling), and launched or settled work is never replayed. The
follow-up review found and corrected an omitted ordinary-crash path: `running` runs with a
persisted planned decision now restore coordinator work without replaying the lead, while
running direct or undecided calls remain untouched. The remaining Phase 10 findings are
unchanged. Focused/affected verification passed 112 tests (8 focused + 104 affected); the
full offline suite reported 588 passed, 2 failed
(the Phase 10h evaluator failures), and 2 skipped.

**Production-path reproduction:** the first lead call asks a durable user question. After
`resume_interrupted("yes")`, the resumed lead records a valid planned decision and returns a final
message. The controller returns `completed`; the child model has zero calls; the child task remains
`queued`, its attempt remains `assigned`, its reservation remains `reserved`, and its plan node
remains `launching`.

**Cause:** the initial completion path calls `_dispatch_admitted_plan_agents()` before committing
terminal state, but the successful `resume_interrupted()` path does not.

**Affected invariant:** resume must restore graph state without dropping or duplicating accepted
work, and every funded child assignment must either execute or reach an explicit terminal state.

**Minimal repair:** route initial and resumed completion through one coordinator/finalization path
that dispatches or explicitly blocks all admitted plan work before the run becomes terminal. Add a
question-then-plan production regression. Reconstruct persisted safe `READY` work on recovery;
`restore_interrupted()` currently considers only blocked runs and does not rebuild coordinator
dispatches for ordinary crash recovery.

### P10-003 — High — Planned cancellation and pre-dispatch failure strand funded state

**Production-path reproduction A:** cancel `RunController.run_instruction()` after two planned
children enter their compiled runtimes. Plan nodes become cancelled/blocked, but the run, lead task,
and lead attempt remain `running`; the lead, lead-continuation, and child reservations all remain
`reserved`.

**Production-path reproduction B:** admit a plan, then let the lead fail before planned dispatch.
The run is `failed`, but the child task is `queued`, its attempt is `assigned`, its node is
`launching`, and the child reservation remains `reserved`. The lead-continuation allowance also
remains reserved when uncertain lead settlement raises before `_release_lead_allowances()`.

**Cause:** the controller's terminal exception handler surrounds lead invocation only, not plan
dispatch. It finalizes only the lead assignment, calls allowance release after an operation that may
raise, and has no run-scoped cleanup/reconciliation for admitted but unexecuted child assignments.
Planned child start also updates only the in-memory task registry; the journal task/attempt stay
queued/assigned until terminal settlement.

**Affected invariant:** terminal state and cost must survive cancellation/failure consistently;
unstarted funded work must release safely, ambiguous provider calls must remain held explicitly,
and journal task state must reflect active execution.

**Minimal repair:** centralize run terminalization across lead invocation and plan dispatch; mark
planned task/attempt start durably; settle known calls, retain only genuinely ambiguous call
reservations, release unstarted child reservations and all releasable lead allowances even when one
assignment needs reconciliation, and atomically persist correlated terminal events. Add separate
cancel-during-plan and lead-fails-before-dispatch regressions.

### P10-004 — High — The deterministic evaluator no longer crosses the decision gate

**Production-path reproduction:** `rtk pytest tests\\unit\\test_eval_runner.py -q` reports
`11 passed, 2 failed`. Both mutation fixtures finish without writing their oracle target because
their first scripted response calls `write_file` without first recording `execution_decision`.
The standalone runner result is `completed=False`, `passed_oracle=False`, with
`File does not exist: result.txt`.

**Cause:** Phase 07 made execution decisions mandatory in the production controller, but the Phase
04/05 fixture model and scripts were not migrated to that contract.

**Affected invariant:** the independent offline evaluator must execute fixtures through the actual
current runtime/tool boundary; passing raw records cannot be generated from a stale orchestration
protocol.

**Minimal repair:** update execution scripts to include an independent valid decision before
operational tool calls, without deriving it from the scoring oracle, and retain the oracle-mutation
and write-suppression independence proofs.

### P10-005 — Critical — Plan tool nodes bypass project trust and exact approval

**Production-path reproduction:** admit a tool node for `python -m pytest` in an untrusted
workspace. `_run_plan_tool_node()` constructs `ExecutionSecurityContext(trusted_project=True)` and
executes it without a user interrupt. Approval-requiring plan commands have empty
session/run/task/action identities and become terminally blocked instead of entering the durable
approval/resume flow.

**Affected invariant:** an accepted plan is not permission; project trust and exact-command
approval apply equally to lead, compatibility-task, agent-plan, and tool-plan paths.

**Minimal repair:** execute tool nodes through the canonical execute boundary with the persisted
trust/security context and correlated approval identity. Add untrusted-project and
approve-then-resume production regressions.

### P10-006 — High — Required blocked or failed plan nodes still produce run success

**Production-path reproduction:** let a planned child return invalid/unverified success evidence.
The node and its dependent become blocked, yet `RunController` persists the lead task and run as
`succeeded`/`completed` and emits `run.completed`.

**Affected invariant:** terminal outcomes must be derived from verified required work; a child
status or lead sentence is evidence, not proof that the accepted plan completed.

**Minimal repair:** inspect terminal plan state before run finalization and wake the lead for bounded
failure synthesis/recovery. Required blocked or failed nodes must not silently become a successful
run.

### P10-007 — High — Exact-command approval resume can claim completion without execution

**Resolution:** fixed by Phase 10c on 2026-09-08. The accepted execution decision is
persisted (migration 13) and restored before checkpoint resume, so approval-interrupt
resume runs the approved command once with the exact approval record consumed. The
production regression asserts the real command effect plus consumption of the exact
approval key. The remaining Phase 10 findings are unchanged.

**Production-path reproduction:** the lead records a direct decision and calls an approval-worthy
`pwsh` command. After approving the exact persisted request and resuming, the run returns
`completed` with scripted completion prose, but the command's marker file is absent and the one-shot
approval is unconsumed.

**Cause:** resume rebuilds a fresh in-memory `ExecutionDecisionGate`; the accepted decision is not
persisted/reloaded. The current TUI test checks prose and a differently keyed `CommandRequest`, not
the actual command effect or exact approval key.

**Affected invariant:** resume restores decision and approval state without fabricating tool
completion or broadening/rekeying authority.

**Minimal repair:** persist the accepted execution decision, restore it before checkpoint resume,
and assert the real command effect plus consumption of the exact approval record.

### P10-008 — High — Compatibility `task` still uses a second scheduler path

**Resolution:** fixed by Phase 10d. Compatibility `task` batches now create a canonical persisted
plan before task/attempt assignment, bind every compatibility task to its plan node, record node
execution before the compiled child lifecycle starts, and settle the same node from the canonical
task result path. A production regression proves the standard task surface leaves one succeeded
plan node rather than an untracked child lifecycle.

**Production-path reproduction:** execute a valid direct-mode compatibility `task` call and inspect
`Journal.plans_for_run()`. The child task/attempt executes, but no single-node `ExecutionPlan` exists;
`_admit_task_batch()` directly creates task, attempt, scheduler, and assignment state.

**Affected invariant:** DeepAgents' standard `task` surface must enter the same persistent plan
admission, coordinator, recovery, cancellation, result, and event services as typed plans.

**Minimal repair:** translate admitted compatibility calls into canonical single-node plans and use
the shared plan dispatcher; remove the parallel lifecycle path only when production regressions
prove compatibility behavior is retained.

### P10-009 — High — Budget-deferred plan nodes retain nonterminal task state

**Production-path reproduction:** use a run budget that funds the lead but not the child frontier.
The plan node becomes blocked, while its journal task remains `queued` and its attempt remains
`assigned`.

**Cause:** the pre-call `RouteFailure` path updates only the in-memory registry and plan result;
`record_settle()` is never called to terminalize the journal task/attempt.

**Affected invariant:** every admitted attempt has one truthful durable lifecycle, including a
pre-call budget block.

**Minimal repair:** atomically persist the route-failure result, task/attempt terminal states,
plan-node transition, and correlated events before returning the blocked result.

### P10-010 — High — Terminal state and terminal event are separate commits

**Production-path reproduction:** source trace of successful controller completion shows
run/task/attempt/session status committed first, followed by budget finalization/checkpoint work and
a separate `_emit_event("run.completed")` transaction. A process exit or settlement exception in
between leaves terminal state without its authoritative terminal event. Similar split writes exist
for task and blocked transitions.

**Affected invariant:** the journal event stream and state transition form one post-commit truth;
rollback or crash must not expose only half of a logical transition.

**Minimal repair:** append each correlated lifecycle event in the same journal transaction as its
state mutation, with subscriber delivery registered on that outer transaction.

## Passing evidence and coverage limits

- `rtk pytest tests\\contract\\test_execution_decisions.py tests\\integration\\test_assignment.py tests\\integration\\test_budget_concurrency.py tests\\integration\\test_lead.py tests\\integration\\test_delegation_controls.py tests\\integration\\test_plan_persistence.py tests\\integration\\test_recovery.py tests\\unit\\test_event_bus.py tests\\unit\\test_execution_policy.py tests\\unit\\test_execution_plans.py tests\\unit\\test_task_registry.py -q`
  — 115 passed.
- `rtk pytest -q` — 578 passed, 2 failed, 2 skipped. The failures are
  `test_evaluation_runner_runs_deterministic_fake_suite` and
  `test_oracle_mutation_changes_scoring_without_changing_execution_record`.
- `rtk pytest tests\\unit\\test_eval_runner.py -q` — 11 passed, 2 failed (the same two failures).
- `python -m ruff check src tests scripts evals benchmarks` — passed.
- `python -m mypy src\\rudder` — passed, 104 source files.
- `python scripts\\smoke.py --fake-provider` — passed.
- Three local `RunController` probes used only scripted fake models and temporary directories to
  reproduce P10-001 through P10-003. Their observed states are recorded above; permanent failing
  regressions belong to the corresponding repair slices so this audit commit does not deliberately
  break the branch.

The two default-suite skips were verified with
`python -m pytest tests\\integration\\test_filesystem_boundary.py tests\\security\\test_workspace_boundaries.py -q -rs`:
symlink creation is unavailable in the current Windows environment, and administrator privileges
are required for the security symlink case. They are not represented as passing evidence. No
provider-live, paid, OAuth, push, publish, tag, remote rename, or legacy operation was attempted.

## Repair sequence

1. **Phase 10b (complete 2026-09-07):** execute discovery checkpoints and admit evidence-backed
   revisions.
2. **Phase 10c (complete 2026-09-08):** restored decision state and dispatched safe planned work after interrupt/crash resume (P10-002 + P10-007).
3. **Phase 10d:** route compatibility tasks through canonical persistent plan admission.
4. **Phase 10e:** make plan/run/task terminal state and events truthful and atomic.
5. **Phase 10f:** reconcile cancellation, failure, and every reservation owner.
6. **Phase 10g:** route plan tool nodes through canonical trust and exact approval policy.
7. **Phase 10h:** migrate the independent evaluator to the required decision contract.
8. **Phase 10i:** rerun the complete graph/accounting review and close the checkpoint only if no
   critical/high finding remains.

Each repair is a separate test-first implementation commit and user check-in. Phase 11 remains
blocked until Phase 10i passes.
