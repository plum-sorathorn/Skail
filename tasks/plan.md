# Live Agentic Test Plan: Skail Core Orchestration

## Objective

Validate Skail through real interactive agent runs rather than pytest fixtures, scripted model
responses, or `scripts/live_check.py`. The run must exercise direct work, multiple selected models,
parallel subagents, adaptive graph execution, human interrupts, queued follow-ups, durable resume,
workspace isolation, routing evidence, and user-facing output quality while keeping total external
provider spend below USD 10.00.

The original plan was executed on 2026-09-22 after catalog refresh and model qualification. The
execution evidence is under `out/live-agentic/`; future reruns should preserve the same gates.

## Non-negotiable constraints

- Drive every scenario through the interactive `skail` TUI with prompts entered by a human/operator.
- Use one durable session for the scenario matrix, including the resume test.
- Select at least three distinct model IDs in that session:
  - `LEAD_MODEL`: strongest tool-capable model used for lead synthesis.
  - `ECONOMY_MODEL`: low-cost tool-capable model used for exploration/testing.
  - `IMPLEMENTER_MODEL`: mid-tier tool-capable model used for code changes.
- Do not use Skail's budget ledger as the spend authority. `/budget` is an output under test only.
- Use provider-side account usage, balance, or billing-dashboard deltas as the authoritative spend
  measurement.
- Never expose credentials in transcripts, screenshots, exports, notes, or shell output.
- Run only in a disposable Git repository. Never use the Skail source checkout as the live agent's
  writable test target.
- Stop immediately for any secret exposure, out-of-workspace write, destructive command, data loss,
  repeated paid call, or provider spend anomaly.

## Success criteria

1. At least three distinct models are selected in one session and at least two are proven by
   persisted assignment records to have executed.
2. A simple request completes directly without child tasks.
3. A bounded code change is implemented and verified by the lead.
4. Two independent child agents run concurrently without exceeding three active children.
5. A typed adaptive plan records independent nodes, a checkpoint, a revision, and terminal states.
6. Model assignment remains sticky within each healthy attempt.
7. A queued follow-up remains visible and runs FIFO after the active foreground request.
8. A human question survives quit/resume and continues without duplicate work or duplicate charge.
9. Workspace isolation prevents edits outside the disposable repository and safely integrates
   accepted child changes.
10. Final responses are human-readable and contain no raw internal JSON, malformed tool payloads,
    duplicate messages, or missing completion state.
11. Every observed defect has reproducible evidence, severity, suspected cause, proposed fix, and a
    regression-test recommendation.
12. Authoritative provider-side spend remains below USD 10.00.

## Spend control independent of Skail

### Hard limits

- Absolute ceiling: **USD 10.00**.
- Normal execution stop: **USD 8.50**.
- Contingency reserve: **USD 1.50**, used only to finish an already-started call or repeat one
  scenario after a clearly diagnosed harness failure.
- Do not pass `--budget` to Skail during this matrix. The runtime budget gate is not the financial
  control for this test.

### Accounting procedure

Before the first provider call:

1. Record provider account usage/balance and timestamp in `out/live-agentic/COSTS.csv`.
2. Record the provider's displayed price for each selected model.
3. If supported, configure a provider-side project/key limit of USD 9.50.
4. Set a local timer for each scenario and note its start/end time.

After every scenario:

1. Refresh the provider's independent usage/billing view.
2. Record the cumulative account delta and per-scenario delta.
3. Compare the provider delta with Skail's exported usage as a product assertion, but never use
   Skail's value to decide whether another paid scenario may start.
4. Stop if cumulative provider spend is at least USD 8.50, the next scenario's allocation cannot
   fit, or provider accounting is delayed/ambiguous by more than USD 0.25.

### Scenario allocations

| Scenario | Maximum USD |
|---|---:|
| Preflight and model selection | 0.00 |
| S1 direct read-only request | 0.10 |
| S2 direct bounded implementation | 0.55 |
| S3 in-session model switch | 0.70 |
| S4 parallel two-child orchestration + queued follow-up | 1.60 |
| S5 adaptive graph with checkpoint and revision | 2.25 |
| S6 interrupt, quit, and resume | 0.75 |
| S7 safety/blocking behavior | 0.75 |
| S8 conditional escalation probe | 1.50 |
| Planned scenario total | **8.20** |
| Unallocated contingency | **1.30** |
| Planned maximum | **9.50** |

If a scenario exceeds its allocation, stop and diagnose before continuing. Do not compensate by
silently reducing evidence collection.

## Test environment

### Disposable workspace

Create `out/live-agentic/workspace` as a new Git repository. It should contain a small Python package
with deterministic offline tests and no external dependencies beyond pytest:

```text
src/live_fixture/
  normalize.py          # identifier normalization behavior
  parser.py             # line/record parsing behavior
  report.py             # aggregation and rendering behavior
  exporter.py           # intentionally absent at baseline
tests/
  test_normalize.py
  test_parser.py
  test_report.py
  test_integration.py
README.md
pyproject.toml
```

Prepare one failing normalization test, two independent unimplemented parser/report behaviors, and
a later integration requirement that depends on both. Commit the baseline so every agent change is
diffable and recoverable. The fixture must not contain secrets, network calls, generated lockfiles,
or links to the Skail source tree.

### Preflight commands

Run these outside the Skail TUI. They are setup/inspection, not test drivers:

```powershell
skail auth check
skail models list
git -C out/live-agentic/workspace status --short
python -m pytest out/live-agentic/workspace/tests -q
```

`skail auth check` must not contact the provider. Record the exact three selected model IDs and their
prices before launch. Reject models with unknown pricing, missing tool support, or unknown structured
output support.

### Model selection rules

- `LEAD_MODEL`: highest-capability qualified model among the affordable candidates.
- `ECONOMY_MODEL`: cheapest qualified model with tools and structured output.
- `IMPLEMENTER_MODEL`: different from both above; favor reliable tool use over maximum context.
- Prefer one provider for all three models to make external cost reconciliation simpler.
- If fewer than three qualified priced models exist, stop. Do not substitute unpriced models.

Launch from the disposable workspace without a Skail budget flag:

```powershell
skail --lead-model <LEAD_MODEL> `
  --agent-model explorer=<ECONOMY_MODEL> `
  --agent-model tester=<ECONOMY_MODEL> `
  --agent-model implementer=<IMPLEMENTER_MODEL> `
  --mode auto --max-agents 3 --delegation auto --workspace worktree
```

In the TUI, open `Alt+P` and verify all three models are selected for future assignments. Record the
session ID shown by onboarding/session controls. Do not change sessions during S1-S7.

## Evidence captured for every scenario

Record the following in `out/live-agentic/RUN_LOG.md` immediately after each scenario:

- Scenario ID, exact prompt, start/end timestamps, and wall time.
- Session ID, run ID, task IDs, attempt IDs, and plan ID when present.
- Selected model set and actual provider/model for every assignment.
- Execution mode (`direct`, `discover`, or `planned`).
- Child peak concurrency and observed ordering.
- Expected outcome versus actual outcome.
- Changed paths and `git diff --stat` in the disposable workspace.
- Verification commands and results reported by Skail, then independently rerun by the operator.
- Provider-side cost delta and cumulative spend.
- `/agents`, `/plan`, `/route`, and `/budget` observations relevant to the scenario.
- Any malformed, duplicated, missing, stale, or overly technical user-facing output.

After S3, S5, S6, and S8, export the session without making a model call:

```powershell
skail sessions export <SESSION_ID> --output out/live-agentic/session-<checkpoint>.json
```

Treat session exports, provider billing, workspace diffs, and independently rerun tests as evidence.
Treat model-authored claims as unverified until corroborated.

## Scenario matrix

### S1 — Direct read-only request (simple)

Prompt:

> Inspect `src/live_fixture/normalize.py` and explain how identifiers are normalized. Do not edit
> files and do not delegate. Cite the relevant file and function, and keep the answer under 120 words.

Expected:

- One lead assignment, no child tasks, no workspace changes.
- `direct` completion and a clean prose response.
- `/agents` shows no children; `/route` shows `LEAD_MODEL`.

Failure signals: delegation despite prohibition, invented paths, raw JSON, missing final response, or
cost above USD 0.10.

### S2 — Direct bounded implementation (small)

Prompt:

> Work directly without delegating. Fix `normalize_identifier` so repeated whitespace and hyphens
> collapse to one hyphen, leading/trailing separators are removed, and existing Unicode letters are
> preserved. Update only the focused tests and run them. Return changed paths and exact verification.

Expected:

- Lead edits only `normalize.py` and its focused test.
- Focused test passes; no child assignment exists.
- Final response is concise and accurately reports the diff and test command.

### S3 — Multiple models in the same session (medium)

1. Use `/model <ECONOMY_MODEL>` and submit:

   > Review `parser.py` for correctness risks only. Do not edit or delegate. Return at most three
   > findings with file references.

2. Use `/model <LEAD_MODEL>` and submit:

   > Re-review the same parser risks, challenge the prior findings, and identify any missed edge
   > case. Do not edit or delegate.

Expected:

- Two new lead assignments use the two requested models.
- Each assignment remains model-sticky for its entire attempt.
- `/route` and the session export agree on model identity and lineage.
- The second response references the prior conversation without replaying internal JSON.

### S4 — Parallel multi-agent orchestration and queueing (complex)

Prompt:

> Use exactly two child agents in parallel. Give one implementer exclusive ownership of
> `src/live_fixture/parser.py` plus `tests/test_parser.py`; give the other exclusive ownership of
> `src/live_fixture/report.py` plus `tests/test_report.py`. Implement the TODO behavior in each
> module, run each focused test, integrate both results, then have the lead run the integration test
> and synthesize one final answer. The write scopes must not overlap.

While children are visibly running, queue with `Ctrl+Enter`:

> After the active run completes, summarize which model handled each child and whether their wall
> times overlapped. Do not modify files.

Expected:

- Exactly two first-level child tasks and no nested delegation.
- Peak child concurrency is two; maximum never exceeds three.
- Distinct write scopes/worktrees and deterministic integration.
- The queued prompt remains visible, then executes once in FIFO order.
- Final integration test passes and the follow-up uses persisted assignment evidence.

### S5 — Adaptive graph execution (very complex)

Prompt:

> Use planned execution. Create two independent read-only discovery agent nodes: one audits the
> fixture CLI/API boundary and one audits test gaps. Add a checkpoint depending on both. At the
> checkpoint, revise the plan from the evidence and add one implementation agent for a `--strict`
> parser option followed by one verification tool node. Persist the plan and revision; do not write
> before the checkpoint is accepted.

Expected:

- Initial plan contains two independent discovery nodes and one dependent checkpoint.
- Discovery nodes may overlap; both are read-only.
- Checkpoint is recorded once, then a higher revision adds implementation and verification.
- Nodes move through legal states without duplicate launch or skipped prerequisites.
- `/plan` and exported plan records agree on IDs, revision, dependencies, and terminal states.
- Final code and tests meet the prompt after integration.

Stop this scenario if the lead repeatedly emits invalid plan JSON, invents dependency IDs, starts a
writer before the checkpoint, or relaunches a settled node.

### S6 — Human interrupt, quit, and durable resume (medium)

Prompt:

> Before creating an exporter, ask me to choose exactly one format: JSON or CSV. Do not create or
> edit `exporter.py` until I answer. After my answer, implement only that format and add a focused
> test.

Procedure:

1. Wait until the TUI shows `WAITING` and the question.
2. Record IDs, then quit cleanly without answering.
3. Resume with `skail -r <SESSION_ID>`.
4. Confirm the same pending question appears once.
5. Answer `JSON` and allow the run to finish.

Expected:

- No write occurs before the answer.
- Resume restores the question, assignment, plan/task state, and transcript once.
- The existing provider call is not replayed or charged twice.
- Only JSON export behavior is implemented and verified.

### S7 — Safety and blocked behavior (medium)

Prompt:

> Create `../outside-skail-live-test.txt` containing `boundary probe`. Do not choose another path if
> that path is denied; report the policy result.

Expected:

- The filesystem boundary rejects the write.
- No outside file appears.
- The run reports `blocked`, not false success or automatic workaround.
- The final response is actionable and does not expose unrestricted tool output.

This scenario must be run only from the disposable workspace. Verify the parent path remains
unchanged with a read-only filesystem check.

### S8 — Conditional escalation probe (complex, optional)

Run only if provider-side cumulative spend is below USD 6.70 after S7.

Prompt:

> Delegate one implementer task to fix the concurrency defect described by
> `tests/test_integration.py`. Preserve the task identity, run the focused test, and if the first
> attempt genuinely fails, use Skail's single escalation path with the recorded failure evidence.
> Do not manufacture a failure and do not retry more than once.

Expected:

- If attempt one fails, attempt two keeps the task ID, gets a new attempt/assignment, excludes the
  failed model, and receives a concise failure handoff.
- If attempt one succeeds, record escalation as **not exercised**. Do not induce a provider error or
  waste spend merely to force the branch.
- No third attempt occurs.

Agentic-only live testing cannot deterministically force a model failure without fake/scripted
adapters. This limitation must be stated in the final report if escalation is not naturally reached.

## Independent verification after the session

Run these outside Skail in the disposable workspace:

```powershell
python -m pytest -q
git status --short
git diff --check
```

Then inspect the exported session and provider dashboard:

- Every task has one parent run and no illegal nested child.
- Every attempt has one sticky assignment.
- Planned node IDs and revisions are stable.
- No duplicate provider call identity or usage record exists.
- Provider-side total is below USD 10.00.
- Skail's displayed/exported total is compared against the provider total and the discrepancy is
  logged, but it is not used retroactively as the spend authority.

## Defect recording

Create `out/live-agentic/BUGS.md`. Add an entry immediately when a defect is observed:

```markdown
## LIVE-### — Short title

- Severity: P0 | P1 | P2 | P3
- Scenario:
- Session/run/task/attempt IDs:
- Model/provider:
- Expected:
- Actual:
- Reproduction steps:
- Evidence paths/screenshots/export fields:
- Provider-side cost impact:
- Suspected layer/root cause:
- Proposed fix:
- Regression test to add:
- Workaround:
- Status: open | fixed | cannot reproduce | deferred
```

Severity rules:

- **P0:** secret exposure, out-of-scope destructive write, unrecoverable data loss, or runaway spend.
  Stop the entire matrix.
- **P1:** duplicate paid call, incorrect model/task identity, illegal graph transition, broken resume,
  unsafe concurrent writers, or incorrect terminal success. Stop the current scenario.
- **P2:** feature malfunction with a safe workaround, stale state, incorrect route/budget display, or
  missing evidence.
- **P3:** copy, alignment, formatting, or minor usability issue.

Create `out/live-agentic/OUTPUT_MISFORMATS.md` for presentation defects. Record the raw observed
shape in a fenced block only after redaction, then the desired human-readable form. Specifically
check for raw JSON responses, Python `repr`, escaped newlines, duplicated final answers, truncated
tool names, broken Markdown/Unicode, stale `RUNNING`/`WAITING` indicators, and queue-order copy.

## Completion report

The final live-test report must include:

- Exact commit tested and exact model IDs/prices.
- Scenario result table: pass, fail, blocked-as-expected, skipped, or not exercised.
- Provider-side spend by scenario and total.
- Assignment/model matrix and peak concurrency evidence.
- Plan/revision/node-state evidence.
- Workspace diff and independent test results.
- All defects and output misformats, sorted by severity.
- Recommended fix order and which regression test should accompany each fix.
- Explicit limitations, including any unexercised escalation or delayed provider accounting.

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Provider accounting is delayed | Spend ceiling uncertainty | Stop at USD 8.50 and reserve USD 1.50; do not start another scenario while ambiguous |
| Model ignores requested execution mode | Graph/delegation feature not exercised | Record as product defect; inspect `/route` and `/plan`; do not rewrite evidence after the fact |
| Worktree integration conflict | Lost or overlapping edits | Disposable Git repo, committed baseline, disjoint write scopes, immediate diff review |
| Natural failure does not occur | Escalation branch remains untested | Mark not exercised; do not force paid failure in an agentic-only matrix |
| TUI state differs from persisted state | Misleading operator view | Compare TUI panels with exported session after checkpoints |
| Output contains secrets or raw provider data | Security incident | Abort, redact evidence, revoke affected credential, classify P0 |
| Queue/resume duplicates a paid call | Excess spend and correctness failure | Stop scenario, capture provider call IDs and export, classify P1 |

## Approval checkpoint

Before live execution, the operator must approve:

- Exact three model IDs and displayed prices.
- Provider-side cap/starting balance evidence.
- Disposable workspace path and baseline commit.
- Planned maximum of USD 9.50 and normal stop at USD 8.50.
- Whether optional S8 is allowed after reviewing spend through S7.

## Execution addendum — 2026-09-22

- Tested Skail commits through `b06a8e2` (decision payload normalization); later queue/cancellation
  fixes are `370475e` and `a4f8af3`.
- Catalog was refreshed with `skail models refresh`; 135 priced models were discovered.
- Selected models and displayed prices:
  - `llmgateway:qwen3.8-max`: $2.00/M input, $6.00/M output; tools and structured output true.
  - `llmgateway:glm-5.3-flash`: $0.07/M input, $0.19/M output; tools and structured output true.
  - `llmgateway:gpt-4.1-nano`: $0.10/M input, $0.40/M output; tools and structured output true.
- Durable session: `a946e3d4-0e4f-46f4-b683-00aca18b5bfc`.
- Results: S1 passed; S2 cancelled after repeated decision/loop behavior; S3 model switch passed
  but review was stopped for a long read-only loop; S4 blocked before child completion; S5 persisted
  a plan/checkpoint and reached an approval conflict. S6-S8 were not run.
- Conservative recorded total: USD 0.437681, including USD 0.349224 in interrupted-call
  estimates; authoritative provider-reported actuals were lower. See `COSTS.csv`.
- No workspace files were changed by the live agents; baseline fixture remained recoverable.
- Open live defects are recorded in `BUGS.md`; presentation defects are in
  `OUTPUT_MISFORMATS.md`.
