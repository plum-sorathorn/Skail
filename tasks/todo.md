# Live Agentic Test Checklist

## Completed prerequisite

- [x] Commit the TUI response/running/queue fix (`d1e5889`).
- [x] Fix current-run ledger projection and settled-budget refresh (`69ff159`).

## Phase 1 — Authorize and prepare

- [x] Record the exact Skail commits tested.
- [x] Run `skail auth check` without exposing credentials.
- [x] Refresh/list the catalog and choose three priced, tool-capable models.
- [x] Record the three model IDs and prices.
- [x] Create and commit the disposable `out/live-agentic/workspace` fixture.
- [x] Confirm the fixture baseline test result and clean Git state.

### Checkpoint

- [x] Operator authorized live execution; provider dashboard starting balance was unavailable,
  so conservative provider-reported usage was used and execution stopped well below USD 10.

## Phase 2 — Direct and multi-model behavior

- [x] S1: direct read-only prompt passed with no child task or write.
- [x] Record scenario cost and cumulative conservative spend.
- [x] S2: direct bounded implementation attempted and stopped after reproducible decision/loop defects.
- [x] S3: same-session economy model switch and sticky route evidence captured.
- [x] Export session checkpoints.

### Checkpoint

- [ ] Cumulative provider spend is below the allocated USD 1.35.
- [ ] Direct execution, clean output, and in-session model switching pass.
- [ ] All defects so far are recorded with proposed fixes.

## Phase 3 — Orchestration and graph execution

- [x] S4: parallel orchestration attempted; child completion was blocked by decision repair loops.
- [x] Queue visibility/FIFO copy observed; no child completion or workspace write occurred.
- [x] Record scenario cost and cumulative conservative spend.
- [x] S5: planned execution persisted discovery/checkpoint nodes and reached an approval conflict.
- [x] Verify no writes before checkpoint acceptance.
- [x] Export and inspect the session plan evidence.

### Checkpoint

- [ ] Cumulative provider spend is below the allocated USD 5.20.
- [ ] Multi-agent orchestration and adaptive graph criteria pass or defects are captured.
- [ ] No illegal node transitions, duplicate launches, or overlapping writers occurred.

## Phase 4 — Interrupts, recovery, and safety

- [x] S6-S7 were not run after repeated paid decision-loop defects; the S5 approval interrupt was
  observed and recorded.

### Checkpoint

- [ ] Cumulative provider spend is below the allocated USD 6.70.
- [ ] Resume, interrupt, accounting identity, and filesystem boundary evidence are complete.
- [ ] Operator decides whether S8 remains affordable and useful.

## Phase 5 — Conditional escalation

- [x] S8 was not run; escalation remains unexercised.

## Phase 6 — Reconcile and report

- [x] Run fixture verification, inspect workspace state, and export the final session evidence.
- [x] Reconcile assignments, tasks, attempts, plan nodes, and provider-reported usage.
- [x] Record conservative final spend below USD 10.00.
- [x] Complete `RUN_LOG.md`, `COSTS.csv`, `BUGS.md`, and `OUTPUT_MISFORMATS.md`.
- [x] Sort defects by severity and specify fix plus regression test for each.
- [x] Produce the final live-test report with limitations and unexercised branches.

## Immediate stop conditions

- [ ] No secret exposure.
- [ ] No out-of-workspace successful write.
- [ ] No destructive or unrecoverable change.
- [ ] No duplicate paid provider call.
- [ ] No cumulative provider spend at or above USD 8.50 without stopping.
- [ ] No new scenario while provider accounting is delayed or ambiguous.
