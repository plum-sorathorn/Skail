# Live Agentic Test Checklist

## Completed prerequisite

- [x] Commit the TUI response/running/queue fix (`d1e5889`).
- [x] Fix current-run ledger projection and settled-budget refresh (`69ff159`).

## Phase 1 — Authorize and prepare

- [ ] Record the exact Skail commit to test.
- [ ] Run `skail auth check` without exposing credentials.
- [ ] Run `skail models list` and choose three priced, tool-capable models.
- [ ] Record `LEAD_MODEL`, `ECONOMY_MODEL`, `IMPLEMENTER_MODEL`, and prices.
- [ ] Record provider-side starting usage/balance.
- [ ] Configure a provider-side USD 9.50 limit when available.
- [ ] Create and commit the disposable `out/live-agentic/workspace` fixture.
- [ ] Confirm the fixture baseline test result and clean Git state.

### Checkpoint

- [ ] Human approves exact models, workspace, and spend controls.
- [ ] No provider calls have been made by the test matrix yet.

## Phase 2 — Direct and multi-model behavior

- [ ] S1: Run the direct read-only prompt; verify no child task or write.
- [ ] Record provider-side scenario cost and cumulative spend.
- [ ] S2: Run the direct bounded implementation; independently rerun focused tests.
- [ ] Record provider-side scenario cost and cumulative spend.
- [ ] S3: Switch to `ECONOMY_MODEL`, run review, switch to `LEAD_MODEL`, re-review.
- [ ] Verify persisted assignments match both selected models and remain sticky.
- [ ] Export the session checkpoint.

### Checkpoint

- [ ] Cumulative provider spend is below the allocated USD 1.35.
- [ ] Direct execution, clean output, and in-session model switching pass.
- [ ] All defects so far are recorded with proposed fixes.

## Phase 3 — Orchestration and graph execution

- [ ] S4: Launch exactly two independent child implementers.
- [ ] Queue the follow-up with `Ctrl+Enter` while children run.
- [ ] Verify peak concurrency two, no nested child, disjoint write scopes, and FIFO release.
- [ ] Independently rerun integration tests and inspect workspace diff.
- [ ] Record provider-side scenario cost and cumulative spend.
- [ ] S5: Run planned execution with two discovery nodes and a checkpoint.
- [ ] Verify no writes before checkpoint acceptance.
- [ ] Verify plan revision adds implementation and verification nodes once.
- [ ] Compare `/plan` with the exported session.
- [ ] Record provider-side scenario cost and cumulative spend.

### Checkpoint

- [ ] Cumulative provider spend is below the allocated USD 5.20.
- [ ] Multi-agent orchestration and adaptive graph criteria pass or defects are captured.
- [ ] No illegal node transitions, duplicate launches, or overlapping writers occurred.

## Phase 4 — Interrupts, recovery, and safety

- [ ] S6: Trigger a human format question and confirm `WAITING` state.
- [ ] Quit before answering, resume the same session, and verify one restored question.
- [ ] Answer `JSON`; verify no duplicate call/work and focused test passes.
- [ ] Export the session checkpoint.
- [ ] Record provider-side scenario cost and cumulative spend.
- [ ] S7: Attempt the explicit out-of-workspace write.
- [ ] Verify blocked status and confirm no outside file was created.
- [ ] Record provider-side scenario cost and cumulative spend.

### Checkpoint

- [ ] Cumulative provider spend is below the allocated USD 6.70.
- [ ] Resume, interrupt, accounting identity, and filesystem boundary evidence are complete.
- [ ] Operator decides whether S8 remains affordable and useful.

## Phase 5 — Conditional escalation

- [ ] If approved and affordable, run S8 once.
- [ ] If attempt one fails naturally, verify exactly one stronger-model attempt.
- [ ] If attempt one succeeds, record escalation as not exercised; do not force failure.
- [ ] Record provider-side scenario cost and cumulative spend.

## Phase 6 — Reconcile and report

- [ ] Run fixture `python -m pytest -q`, `git status --short`, and `git diff --check`.
- [ ] Export the final Skail session.
- [ ] Reconcile every assignment, task, attempt, plan node, and provider call identity.
- [ ] Record final provider-side spend; confirm it is below USD 10.00.
- [ ] Compare Skail budget output with provider accounting as a product assertion only.
- [ ] Complete `RUN_LOG.md`, `COSTS.csv`, `BUGS.md`, and `OUTPUT_MISFORMATS.md`.
- [ ] Sort defects by severity and specify fix plus regression test for each.
- [ ] Produce the final live-test report with limitations and unexercised branches.

## Immediate stop conditions

- [ ] No secret exposure.
- [ ] No out-of-workspace successful write.
- [ ] No destructive or unrecoverable change.
- [ ] No duplicate paid provider call.
- [ ] No cumulative provider spend at or above USD 8.50 without stopping.
- [ ] No new scenario while provider accounting is delayed or ambiguous.
