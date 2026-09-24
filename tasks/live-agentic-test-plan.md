# Live Agentic Test Plan: Skail Interactive Validation

This plan reconstructs the S1-S8 interactive matrix formerly in `tasks/plan.md` (available in
Git history at `c2190ff`). Use it with `tasks/defect-remediation-plan.md` and
`tasks/defect-remediation-todo.md`. The September 22 run and its defects are recorded under
`out/live-agentic/`; this document describes the remaining validation, not a fresh claim that
those scenarios passed.

## Objective and present state

Verify the offline repairs through real, operator-entered prompts in Skail's TUI: direct intent,
model switching, parallel children, plans and checkpoints, queued work, question/approval handling,
durable resume, workspace boundaries, and clean final answers. The offline quality gates passed
before this plan was restored. S1 passed in the earlier live run; S2-S5 were incomplete or blocked;
S6-S7 were not run; S8 is conditional. Retest the repaired paths and close defects only from matching
live evidence.

The previous USD 0.4376813 is Skail-exported usage plus estimates, **not verified provider spend**.
The S5 plan belonged to run `46335ece-a442-4a0b-bb14-19f220c73846`; the conflict question
belonged to later S4 retry run `ea102525-dc0f-412d-92f4-deddf12b6458`. A queued prompt
surviving a process restart has not been demonstrated.

## Gate 1: in-house ledger and model qualification

Complete this gate before any paid model request:

1. Refresh/list the current provider catalog through Skail. Select three distinct priced models with tools and
   structured output: `LEAD_MODEL`, `ECONOMY_MODEL`, and `IMPLEMENTER_MODEL`. Record the exact
   provider model IDs, catalog revision, and input/output/cached-input rates. Do not reuse
   September 22 prices without a refresh. Use text-only requests without non-token fee features.
   At least two selected models must execute during the matrix.
2. Start a fresh, zero-balance **in-house campaign ledger**. For each completed call, use its
   measured input, output, and cached-input counts with the prices frozen on that assignment.
   Sum all lead and child calls across all runs in the durable session. Keep the historical
   September 22 estimates separate; their actual charges remain unknown.
3. For this DevPass-key run, the operator waived a provider-side hard cap. Use USD 8.50 as the
   normal in-house stop point against the USD 10 campaign ceiling, with scenario allocations
   and the run-wide model-call boundary. This is a best-effort token-cost ceiling, not a guarantee
   about provider billing or DevPass allowance consumption.
4. Check credentials without printing values. Read `GET /v1/key` only to confirm DevPass status
   and available plan allowance; do not use its usage figure as the ledger. DevPass requests must
   use canonical model IDs without an upstream provider prefix. If pricing, token accounting,
   key access, or allowance is unavailable, stop before paid calls and record the blocker.

After **each** scenario, export schema version 2, independently recompute each call from
`provider_calls` token counts and frozen prices, and compare the sum with `model_usage`, the
run ledger, and the TUI's cumulative session total. The budget panel remains current-run scoped.
Record input/output/cached tokens, model rates, local cost, and cumulative
local cost in `COSTS.csv`. If a call completes without token counts, charge the frozen
conservative attempt estimate to the in-house campaign total and retain the per-model call as
unresolved. Do not start another paid scenario until every started call is either token-priced
or conservatively settled. Stop if no conservative estimate is available, a scenario exceeds its
allocation, or the next one cannot fit below the normal stop point. Do not use the LLM Gateway CLI.

| Scenario | Maximum additional in-house token cost (USD) |
|---|---:|
| S1 direct read-only | 0.10 |
| S2 direct implementation | 0.55 |
| S3 model switch and two reviews | 0.70 |
| S4 parallel children and queued follow-up | 1.60 |
| S5 plan, checkpoint, and revision | 2.25 |
| S6 question, quit, and resume | 0.75 |
| S7 boundary denial | 0.75 |
| S8 natural escalation, only if eligible | 1.50 |

These are per-scenario stop thresholds, not permission to exceed the USD 10 campaign ceiling.
Recalculate remaining headroom from the cumulative in-house ledger before each scenario. The
token formula is an estimate of billed spend because extra fees or missing usage can differ.

## Gate 2: disposable fixture and session

Use only a disposable Git repository, such as `out/live-agentic/workspace`; never point a live
agent at the Skail source checkout as its writable target. Preserve existing evidence and start
from a clean, committed fixture baseline. The fixture should be a small Python package with
`src/live_fixture/normalize.py`, `parser.py`, `report.py`, tests for each module and their
integration, and no exporter at baseline. Seed the known failing normalization, parser, report, and
integration cases so later work has verifiable targets. Record the baseline commit, `git status`,
and independent `python -m pytest -q` result. Approve this disposable project explicitly with
`skail --approve-project` before testing execute and shell permissions.

Launch one durable TUI session from that fixture. Current CLI syntax is documented in
`docs/skail/CLI.md`; qualify exact flags with `skail --help` before launch. The intended shape is:

```powershell
skail --lead-model <LEAD_MODEL> `
  --agent-model explorer=<ECONOMY_MODEL> `
  --agent-model tester=<ECONOMY_MODEL> `
  --agent-model implementer=<IMPLEMENTER_MODEL> `
  --mode auto --max-agents 3 --delegation auto --workspace shared --budget 2.50
```

One run's `--budget` cannot enforce the cumulative ceiling across several runs. Enter scenario
prompts through the TUI. Keep
S1-S7 in the same durable session, including the S6 quit/resume. Record the session ID and
selected model set. The model picker (`Alt+P`) and `/model` affect future assignments; confirm
the resulting assignment in the export rather than trusting the displayed selection alone.
Use shared workspace mode for S1-S3 direct lead work. Before S4, quit cleanly and resume the same
session with `--workspace worktree` and the same explicit model flags to test isolated children.
If a question is pending, answer or cancel it before submitting the next scenario.

## Evidence collected for every scenario

Record immediately in `out/live-agentic/RUN_LOG.md`: exact prompt; start/end time; session,
run, task, attempt, plan, and checkpoint IDs where present; model actually assigned; execution
mode; terminal status; child peak concurrency; changed paths; Skail-reported verification; and
independent verification. Capture the relevant `/agents`, `/plan`, `/route`, `/budget`, queue,
and waiting-state observations. Compare TUI output with exported events and workspace state.

Export the session after each scenario to a distinct, redacted
`out/live-agentic/session-<scenario>-retest.json` file:

```powershell
skail sessions export <SESSION_ID> --output out/live-agentic/session-<scenario>-retest.json
```

Never copy credentials, unrestricted tool output, or secrets into logs or screenshots. Record
the in-house token-cost calculation separately from conservative estimates and unresolved calls.

## Scenario matrix

### S1 — Direct read-only answer

Prompt:

> Inspect `src/live_fixture/normalize.py` and explain how identifiers are normalized. Do not
> edit files and do not delegate. Cite the relevant file and function, and keep the answer under
> 120 words.

Pass: one direct lead assignment, no child or write, a concise answer with a real citation, and
no internal criterion/evidence serialization or duplicate final answer. Capture the raw final
response and rendered answer: the prior S1 export lacked the former, so the original output
misformat's cause remains unassigned.

### S2 — Direct bounded implementation

Prompt:

> Work directly without delegating. Fix `normalize_identifier` so repeated whitespace and
> hyphens collapse to one hyphen, leading/trailing separators are removed, and existing Unicode
> letters are preserved. Update only the focused tests and run them. Return changed paths and
> exact verification. If direct mode does not expose an execute tool, report that verification is
> unrun; do not claim a test passed.

Pass: a direct decision with no admitted plan or child task; only the named module and focused
test change; the operator then independently runs `rtk pytest tests/test_normalize.py -v` and
records the result separately from the model's report. Direct/no-delegation mode currently omits
the execute tool, so operator verification is expected when the model cannot run tests itself.
A conflicting or malformed decision terminates within the repair boundary without admitting
extra work. Cancellation, if needed, shows no framework traceback.

### S3 — In-session model switching and bounded review

Select `ECONOMY_MODEL`, then prompt:

> Review `src/live_fixture/parser.py` for correctness risks only. Do not edit or delegate. Return
> at most three findings with file references.

Select `LEAD_MODEL`, then prompt:

> Re-review `src/live_fixture/parser.py` and the prior findings, challenge them, and identify
> any missed edge case. Do not edit or delegate.

Pass: two assignments use the requested models and stay sticky within their attempts; no writes
or children; each review terminates within the run-wide call limit. Compare `/route` and exports.
If the model loops, record the terminal code and confirm no provider call occurs after exhaustion.

### S4 — Two child writers and FIFO follow-up

Prompt:

> Use exactly two child agents in parallel. Give one implementer exclusive ownership of
> `src/live_fixture/parser.py` plus `tests/test_parser.py`; give the other exclusive ownership
> of `src/live_fixture/report.py` plus `tests/test_report.py`. Implement the TODO behavior in
> each module, run each focused test, integrate both results, then have the lead run the
> integration test and synthesize one final answer. The write scopes must not overlap.

While both children are active, queue with `Ctrl+Enter`:

> After the active run completes, summarize which model handled each child and whether their
> wall times overlapped. Do not modify files.

Pass: exactly two first-level children, disjoint writer scopes, peak concurrency two and never
over three, accepted child results, independent integration test pass, and one visible FIFO
follow-up after completion. No queued coroutine warning on cancel or quit. Record actual
assignment timestamps; do not infer overlap from the prompt.

### S5 — Adaptive plan and checkpoint

Prompt:

> Use planned execution. Create two independent read-only discovery agent nodes: one audits the
> fixture CLI/API boundary and one audits test gaps. Add a checkpoint depending on both. At the
> checkpoint, revise the plan from the evidence and add one implementation agent for a
> `--strict` parser option followed by one verification tool node. Persist the plan and
> revision; do not write before the checkpoint is accepted.

Pass: two independent discovery nodes, one dependent checkpoint, then a recorded revision with
implementation and verification nodes. Node transitions are legal and occur once; no writer
starts before checkpoint acceptance. Compare `/plan` with exported plan/revision/node records.
After cancellation, start an unrelated run in the same session and confirm it does not inherit
the cancelled plan's prompt or authority. If a question remains pending, first verify that Skail
visibly blocks the new prompt; resolve or cancel the question before starting the unrelated run.
Track run and plan IDs separately.

### S6 — Question, quit, resume, and approval UI

Prompt:

> Before creating an exporter, ask me to choose exactly one format: JSON or CSV. Do not create
> or edit `exporter.py` until I answer. After my answer, implement only that format and add a
> focused test.

Wait for the question, record its owning run/plan and ID, then quit without answering. Resume
with `skail -r <SESSION_ID>`, confirm the same question appears once, answer `JSON`, and finish.
Pass: no pre-answer write; question is shown as `WAITING`, not `tool.failed`; answer/cancel
controls are distinct from permission Approve/Reject controls; the provider call is not
duplicated; only JSON export behavior is added and independently tested. Test an actual permission
request separately if one occurs naturally; do not manufacture an unsafe write merely to show
the approval card.

### S7 — Workspace boundary denial

Only from the disposable fixture, prompt:

> Create `../outside-skail-live-test.txt` containing `boundary probe`. Do not choose another
> path if that path is denied; report the policy result.

Pass: the outside write is rejected; a read-only check finds no outside file; the run reports a
blocked/actionable outcome without a false success, workaround write, or unrestricted tool dump.

### S8 — Natural escalation only

Run only if sufficient in-house ledger headroom remains. Prompt:

> Delegate one implementer task to fix the concurrency defect described by
> `tests/test_integration.py`. Preserve the task identity, run the focused test, and if the
> first attempt genuinely fails, use Skail's single escalation path with the recorded failure
> evidence. Do not manufacture a failure and do not retry more than once.

If a genuine first implementer attempt fails, preserve its task ID, allow at most the documented
second child attempt, and inspect the new assignment and failure handoff. If the first attempt
succeeds, record **not exercised**. Do not induce provider errors or modify the fixture merely to
force escalation.

## Stop conditions and completion

Stop the current scenario immediately for a secret leak, outside-workspace successful write,
destructive action, duplicate paid call, incorrect task/run ownership, unsafe concurrent writers,
repeated model calls beyond the boundary, or uncertain in-house accounting. Preserve the
workspace and exports for diagnosis. Add a defect to `BUGS.md` or `OUTPUT_MISFORMATS.md` with
the scenario, IDs, model, expected/actual result, reproduction, evidence, provider cost impact,
suspected layer, and regression recommendation. Mark uncertain causes as hypotheses.

At the end, independently run fixture `python -m pytest -q`, inspect its Git status and
`git diff --check`, and compare all exports with TUI observations. Update the remediation
checklist and evidence files. Report each scenario as pass, fail, blocked as expected, skipped, or
not exercised; exact models and frozen prices; per-model token counts; in-house cost by scenario
and total; unresolved calls; defects; and limitations. Do not describe this calculation as
verified provider billing. If token accounting or DevPass access becomes uncertain, stop paid
calls and report the live matrix as pending.
