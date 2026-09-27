# Live Agentic Test Plan: Skail Interactive Validation

This plan reconstructs the S1-S8 interactive matrix formerly in `tasks/plan.md` (available in
Git history at `c2190ff`). Use it with `tasks/remediation-2026-09-24-plan.md` and
`tasks/defect-remediation-todo.md`. The September 22 run and its defects are recorded under
`out/live-agentic/`; this document describes the remaining validation, not a fresh claim that
those scenarios passed.

## Objective and campaign history

Verify the offline repairs through real, operator-entered prompts in Skail's TUI: direct intent,
model switching, parallel children, plans and checkpoints, queued work, question/approval handling,
durable resume, workspace boundaries, and clean final answers. The offline quality gates passed
before this plan was restored. S1 passed in the earlier live run; S2-S5 were incomplete or blocked.
The latest S6 retry raised and restored a real `user.question`, accepted `JSON`, then completed with
a stale blocked summary and no workspace changes. A fresh continuation created the JSON exporter and
focused test but failed at the 32-call limit after repeated inspections; S6 remains incomplete. S7
passed the workspace-boundary denial. S8 was not exercised because the fixture has no natural
concurrency defect; no failure was forced. In that earlier campaign, the last corrected S4
prompt started run
`7aa2bdab-ffea-470f-b8bc-6ab5e1e5e342`, but the lead call was interrupted before an execution
decision. No plan or child was admitted and the fixture stayed unchanged. The call has no token
counts; its USD 0.175416 assignment estimate is included as a conservative local stop charge, while
provider usage remains unresolved. Continue only with a new assignment; never replay that call.
The attempted relaunch used a non-TTY shell after PowerShell PTY creation failed. `skail --resume`
with no prompt then executed an empty headless instruction; this is not evidence that the TUI queue
survives restart. That command was issued from the Skail repository root, not the disposable fixture;
the task was read-only and no fixture files changed. A later TUI probe succeeded through `cmd.exe`.
S4 remains incomplete after two reservation-adjusted fixture runs: both admitted and launched GLM
implementers concurrently, then each failed ambiguously and cancelled its sibling. No accepted child
results or FIFO follow-up. Four final-run GLM calls without reliable usage were conservatively settled.
The corrected local campaign stop total is USD 2.594404734; S4 used USD 1.512342744 of USD 1.60.
Do not replay ambiguous assignments.

Per-call reconciliation across the seven latest schema-v2 exports found 328 unique call IDs and no
`model_usage` versus stored-call-cost mismatches. The current local campaign has 296 priced calls
recomputed at USD 1.803778734 and ten tokenless calls conservatively settled at USD 0.783784. One
CSV scenario row repeated another run's tokens by USD 0.006842; its measured cost is corrected, and
the same amount is retained as an explicit cumulative-stop buffer so the user-authorized historical
stop remains USD 2.594404734. `out/live-agentic/CALL_COST_AUDIT.csv` contains every call calculation.
The 22 older calls are outside this DevPass campaign: 16 measured calls reprice to USD 0.173399080
locally and six have no token counts. The earlier exported amounts and actual provider billing remain
unknown.

The first six S5 attempts were: run d58218a1-ee25-48ab-888d-dbab789a5a1f admitted a plan but
both Qwen3.8 Flash explorers failed before the checkpoint (USD 0.053850454). Run
9175536d-c3f2-45f7-840d-9a9f4a33e3a8 failed on an ambiguous Qwen3.8 Max lead call, locally settled
at USD 0.177912. Run ee06f5c4-ab20-41b5-8bd1-2e66c2d2f1dc admitted a plan but both GPT-4.1
explorers failed before the checkpoint (USD 0.047752). Run 9761855e-759e-4428-8f76-1df5e7bedeeb
was rejected before admission because the agent nodes omitted required resource_scopes (USD
0.011808). Runs 464af106-673d-4246-9686-cb948d6c5c7c and
cd1bcae5-4e25-42fe-8a50-f733ae9a0543 both completed without an admitted plan or child tasks
(USD 0.018650 and USD 0.008718). The first said its plan was rejected; the second falsely claimed
two explorers had launched. Those six runs cost USD 0.318690454, with no accepted discovery results,
checkpoint completion, revision, or implementation.

Separate S5 follow-up evidence: TUI startup run `9400f0ee-45f7-4a2f-98d0-142d25f525fc` sent
`/help` through DevPass GPT-4.1 as a model task, costing USD 0.009016; it admitted no plan or child.
Run `b8d63cc7-2399-43c0-9337-44601eaf22b8` was launched with a literal leading quote and the
child-scoped phrase “Do not delegate further”; the resolver chose direct mode and rejected the
planned decision (USD 0.012848). Run `9c251173-023c-4307-ae8e-1a7726adebc6` received unquoted
planned intent, but two decision attempts failed `decision.plan_invalid`; no plan or child was
admitted (USD 0.015254). The latest run `f76cbd54-caf1-429d-be0e-19a71b54db2a` admitted the
intended three-node plan, then both auto-routed GPT-4.1 explorers failed before accepted results;
the checkpoint blocked without revision or implementation (USD 0.040940). Final retry
`071ba5b0-5c91-479d-bb14-74db2e951997` admitted plan `04e5799a-0e2a-4b91-87e1-b95afa40c26c`,
but both GPT-4.1 explorers failed before accepted results; retries were `auto_ineligible` and the
checkpoint blocked. Twelve calls used 26,006 input, 1,266 output, and 17,920 cached tokens for
USD 0.035260 locally. No files changed. S5 use including all follow-ups is USD 0.432008454 of
USD 2.25, leaving USD 1.817991546. Actual provider spend is unknown; S5 remains incomplete.

Offline fixes include the child TaskResult response contract (commit 935ae49), lead plan guidance
with required effect and resource scopes, runtime enforcement for explicit planned execution
(including after question resume), child-scoped “do not delegate further” handling, and an explicit
user-question requirement that gates decisions and operations until an accepted answer. Regressions
reproduced the false successes, scope conflict, and missing question interrupt before the fixes.
The final offline gates after the relative-artifact package path regression pass: Ruff, mypy,
unit/contract (900 passed, 2 skipped), smoke, and three full-suite runs (1185 passed, 5 skipped
each). `scripts/package_check.py` also built, inspected, and installed a real wheel and sdist, and
the packaging tests reused that wheel. Earlier live scenarios used the DevPass provider alias; a
fresh catalog and price refresh is required before the next provider call. The user confirmed
DevPass approves Skail and waived a provider-side hard cap. Use the USD 8.50 in-house stop under the
best-effort USD 10 ceiling. Provider billing remains unknown. S5 remains incomplete: the latest
plan admitted, but both explorers failed before the checkpoint, and the exports omit their result
details and failure category. Safe offline diagnostics now capture those categories; the historical
cause remains unknown and another S5 attempt is withheld. S6 has live question display/resume
confirmation, but its accepted answer was followed by a stale waiting summary; an offline guard now
blocks that false completion. A separate continuation created files but failed at the 32-call limit.
S6 remains incomplete pending a same-run retest. S7 passed its boundary denial. S8 was not exercised
because the fixture has no natural concurrency defect to escalate.
Retest repaired paths and close defects only from matching live evidence.

The previous USD 0.4376813 is Skail-exported usage plus estimates, **not verified provider spend**.
The S5 plan belonged to run `46335ece-a442-4a0b-bb14-19f220c73846`; the conflict question
belonged to later S4 retry run `ea102525-dc0f-412d-92f4-deddf12b6458`. A queued prompt
surviving a process restart has not been demonstrated.

## Current retest status (2026-09-26)

S1 and S3 passed their applicable read-only checks; S2's
correction passed its focused operator test but final TUI text was not captured. S4 remains
failed after bounded two-child attempts because no child `TaskResult` was accepted and no
checkpoint or FIFO follow-up completed. A previously omitted S4 run
`be73b1cc-6df8-43a0-8d38-3e8d8da76bc6` added 16 completed calls at USD 0.019030400.
S6 run `5a216e69-9126-49b0-849f-9811d5ba0a35` accepted `JSON` and then completed with a
stale “Awaiting your selection” summary; `7b54772` blocks that wording offline. The later
same-run retest `e12b7b3e-e2a9-402a-a0bb-8e9e34c14c96` restored the same question after
quit/resume and accepted `JSON`, but still completed with output status `waiting_for_user`, a stale
summary, and no workspace changes. A new failing/green regression and runtime guard now cover
that status. A second post-fix run `b4235f5b-0c92-419b-9803-adbc4f00c8ff` restored the question,
accepted `JSON`, and emitted `run.completed` with output status `blocked`, a stale waiting summary,
and no changes. The completed lifecycle event is inconsistent with the nested blocked output, and
S6 still fails. The final S6 TUI transcript view did not show a readable completion. At the S6 checkpoint, its two
exports added six calls costing USD 0.023594000 locally; all 219 retest IDs were audited once at
USD 0.378003976, with cumulative local cost USD 2.972408710. S6 has USD 0.584124 remaining and
remains failed. S5 is withheld pending diagnosis; S7 remains passed. S8 has now been attempted
under its natural-failure rule and failed at result validation/retry eligibility. Its 25 calls cost
USD 0.024644374 locally; all 244 retest IDs are audited once at USD 0.402648350. Cumulative local
cost is USD 2.997053084, leaving USD 5.502946916 to the USD 8.50 stop and USD 7.002946916 to the
USD 10 ceiling. S8 has USD 1.475355626 remaining in its allocation. Provider billing remains
unknown.

## Gate 1: in-house ledger and model qualification

Continue the existing retest subledger; record a new clean fixture commit, selected model
assignments, and frozen price snapshot before the next scenario. Preserve the historical USD
2.594404734 campaign ledger separately; never reset or overwrite its evidence. Add each new
charge to the current cumulative USD 2.997053084 for the best-effort USD 10 ceiling and
normal USD 8.50 local stop. Current local headroom is USD 7.002946916 to the ceiling and USD
5.502946916 to the normal stop. Reassign scenario allowances within that headroom.

Complete this gate before any paid model request:

1. Refresh/list the current provider catalog through Skail. Select three distinct priced models with tools and
   structured output: `LEAD_MODEL`, `ECONOMY_MODEL`, and `IMPLEMENTER_MODEL`. Record the exact
   provider model IDs, catalog revision, and input/output/cached-input rates. Do not reuse
   September 22 prices without a refresh. Use text-only requests without non-token fee features.
   At least two selected models must execute during the matrix.
2. Continue the existing **in-house retest subledger**. For each completed call, use its
   measured input, output, and cached-input counts with the prices frozen on that assignment.
   Sum all lead and child calls across all runs in the durable session. Keep the historical
   September 22 estimates separate; their actual charges remain unknown.
3. For this DevPass-key run, the operator waived a provider-side hard cap. Use USD 8.50 as the
   normal in-house stop point against the USD 10 campaign ceiling, with scenario allocations
   and the run-wide model-call boundary. This is a best-effort token-cost ceiling, not a guarantee
   about provider billing or DevPass allowance consumption.
4. The user confirmed DevPass approves Skail as an interactive client. Check credentials without
   printing values. If `GET /v1/key` is available, record DevPass status and plan allowance for
   context only; do not use it as the spend ledger or require an independently verified billing
   baseline or provider-side cap for this run. Use canonical model IDs without an upstream provider
   prefix. Continue while frozen per-model prices and reliable token counts or conservative local
   estimates are available. If the key is invalid or a call cannot be locally priced or settled,
   stop before the next paid call. Missing provider billing evidence alone does not block the test.

After **each** scenario, export schema version 2, independently recompute each call from
`provider_calls` token counts and frozen prices, and compare the sum with `model_usage`, the
run ledger, and the TUI's cumulative session total. Compare the complete latest session's call-ID
set with `CALL_COST_AUDIT.csv` so earlier runs cannot be omitted. The budget panel remains
current-run scoped.
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

Use only a disposable Git repository; never point a live agent at the Skail source checkout as its
writable target. Preserve all existing fixtures, worktrees, and S6 artifacts under `out/live-agentic`.
For the next writable scenario, make a fresh disposable fixture from the clean baseline commit
`113ed8c9f69b0b6dfca596b0dc86052d3b63dc3a` and record its path/status before launch.
The fixture should be a small Python package with
`src/live_fixture/normalize.py`, `parser.py`, `report.py`, tests for each module and their
integration, and no exporter at baseline. Seed the known failing normalization, parser, report, and
integration cases so later work has verifiable targets. Record the baseline commit, `git status`,
and independent `python -m pytest -q` result. Approve this disposable project explicitly with
`skail --approve-project` before testing execute and shell permissions.

Launch one durable TUI session from that fixture. For a standalone S6 retest, a fresh session is
acceptable if the old S6 run is already terminal; quit and resume that new run in its own session.
Confirm `stdin.isatty()` and `stdout.isatty()` in the actual launch path. A `cmd.exe /k` PTY was
verified during the audit, while a separate shell child reported `True False`. Current CLI
syntax is documented in `docs/skail/CLI.md`; qualify exact flags with `skail --help` before
launch. The intended shape is:

```powershell
skail --lead-model <LEAD_MODEL> `
  --agent-model explorer=<ECONOMY_MODEL> `
  --agent-model tester=<ECONOMY_MODEL> `
  --agent-model implementer=<IMPLEMENTER_MODEL> `
  --mode auto --max-agents 3 --delegation auto --workspace shared --budget 2.50
```

One run's `--budget` cannot enforce the cumulative ceiling across several runs. Enter scenario
prompts through the TUI. For a new full matrix, keep S1-S7 in one durable session; for focused
retests, preserve same-run ownership across the scenario's quit/resume. Record the session ID
and selected model set. The model picker (`Alt+P`) and `/model` affect future assignments; confirm
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

> Use planned execution. Call `execution_decision` before any operational tool. Use exactly two
> implementer child agents in parallel. Use these `execution_decision` arguments with exactly two
> agent nodes and one checkpoint node; do not add
> any other agent or tool nodes:
>
> ```json
> {
>   "mode": "planned",
>   "objective": "Implement the independent parser and report fixture TODOs",
>   "constraints": ["Use exactly two implementer agents with disjoint resource scopes"],
>   "reason": "The two modules have independent write ownership and focused tests.",
>   "plan": {
>     "schema_version": 1,
>     "policy_version": "adaptive-v1",
>     "revision": 1,
>     "nodes": [
>       {
>         "local_id": "parser",
>         "kind": "agent",
>         "objective": "Implement the parser TODO and focused test",
>         "effect_scope": "workspace_write",
>         "resource_scopes": ["src/live_fixture/parser.py", "tests/test_parser.py"],
>         "acceptance_criteria": ["rtk pytest tests/test_parser.py -q passes"],
>         "task_features": {"profile": "implementer"}
>       },
>       {
>         "local_id": "report",
>         "kind": "agent",
>         "objective": "Implement the report TODO and focused test",
>         "effect_scope": "workspace_write",
>         "resource_scopes": ["src/live_fixture/report.py", "tests/test_report.py"],
>         "acceptance_criteria": ["rtk pytest tests/test_report.py -q passes"],
>         "task_features": {"profile": "implementer"}
>       },
>       {
>         "local_id": "integrate",
>         "kind": "checkpoint",
>         "objective": "Review the two completed child results",
>         "depends_on": ["parser", "report"],
>         "effect_scope": "read"
>       }
>     ]
>   }
> }
> ```
>
> Each child must return one JSON `TaskResult` using its assigned task ID, an allowed status,
> summary, changed paths, artifacts as objects with `kind` and `path`, and a verification entry for
> its acceptance criterion. For a passing result, use `status: "succeeded"`. A write-capable
> verification must include `evidence_ref` as `{"kind":"file","path":"<scoped file>","digest":"<sha256>"}`;
> compute the digest from the exact file bytes with Python and use the actual task ID. Do not use
> strings or null for `evidence_ref`, and do not return prose outside the JSON object. Write only
> within the node's `resource_scopes`.
>
> Delegate only those two independent writers. Each child runs its focused test. After the
> checkpoint and integration, return one final answer with changed paths and focused test results.
> Do not add an integration agent or plan tool node. The operator runs
> `rtk pytest tests/test_integration.py -v` after the active run completes and records that
> verification separately. After `execution_decision` admits the plan, do not call `task()` to
> recreate its agent nodes. Return control so Skail dispatches the admitted nodes. The write scopes
> must not overlap.

While both children are active, queue with `Ctrl+Enter`:

> After the active run completes, summarize which model handled each child and whether their
> wall times overlapped. Do not modify files.

Pass: exactly two implementer agent nodes, one checkpoint depending on both, disjoint `resource_scopes`, peak
concurrency two and never over three, accepted child results, no writes outside declared scopes,
operator-run integration test pass, and one visible FIFO
follow-up after completion. No queued coroutine warning on cancel or quit. Record actual
assignment timestamps; do not infer overlap from the prompt. A count or scope conflict must be
rejected before plan admission and repaired within the bounded decision allowance.

Current S4 disposition: failed/incomplete after bounded live attempts. The previously omitted
run `be73b1cc-6df8-43a0-8d38-3e8d8da76bc6` used 16 completed DevPass lead/child calls at
USD 0.019030400 and also blocked before accepted results. With that run included, S4 retest
cost is USD 0.263971288 of its USD 1.60 allocation; USD 1.336028712 remains. Do not run
another paid S4 attempt until deterministic child-result evidence establishes a corrective
action. The `d92b4b9` scope repair passed an offline denied-write regression; later live
worktrees had no out-of-scope file, but no direct denied-write attempt was observed.

### S5 — Adaptive plan and checkpoint

The first plan was rejected because the agent nodes omitted resource_scopes. Later plans admitted but
explorers returned no accepted results. The next attempt must use fresh run/task IDs, include
non-empty disjoint resource_scopes for the initial agents, and leave the explorer profile unpinned so
a failed first attempt can select another qualified model.

**Eligibility gate:** the latest exports contain no child result, safe failure category, or validation
path for the failed explorers, so their exact cause is unknown. New offline diagnostics make future
failures visible but do not diagnose those past failures. Do not pay for S5 again until offline
evidence establishes a corrective action or a distinct qualified route. S5 is currently withheld.

Prompt:

> Use planned execution. Submit an initial plan with two independent read-only discovery agent nodes
> and one dependent checkpoint. Do not add the implementation agent or a verification tool node until
> the checkpoint is accepted. The agent nodes need distinct, non-empty resource_scopes and an explicit
> read effect_scope; use profile explorer for both. One audits the fixture CLI/API boundary, the other
> audits test gaps. Each returns at most five concise findings with path:line references and uses no
> more than six read-only tool calls. Do not delegate further.
>
> At the checkpoint, revise the plan using only the two reports. Preserve the initial node IDs and
> dependencies. Add one implementation agent with profile implementer, effect_scope workspace_write,
> resource_scope src/live_fixture/parser.py, dependency on the checkpoint, and acceptance criteria for
> implementing --strict while preserving permissive behavior. Use PlanRevision expected_revision=1,
> added_nodes, justification, and evidence_refs fields. Do not add a verification tool node; after the
> agent run ends, the operator runs python -m pytest tests/test_parser.py -q.

Initial revision-1 plan shape:

```json
{
  "schema_version": 1,
  "policy_version": "adaptive-v1",
  "revision": 1,
  "nodes": [
    {
      "local_id": "audit-cli-api",
      "kind": "agent",
      "objective": "Audit the fixture CLI/API boundary and identify strict-parser hook points",
      "effect_scope": "read",
      "resource_scopes": ["src/live_fixture/parser.py"],
      "task_features": {"profile": "explorer"},
      "acceptance_criteria": ["Return findings with path:line evidence"]
    },
    {
      "local_id": "audit-test-gaps",
      "kind": "agent",
      "objective": "Audit parser test coverage and identify strict-option test gaps",
      "effect_scope": "read",
      "resource_scopes": ["tests/test_parser.py"],
      "task_features": {"profile": "explorer"},
      "acceptance_criteria": ["Return findings with path:line evidence"]
    },
    {
      "local_id": "discovery-checkpoint",
      "kind": "checkpoint",
      "objective": "Review both discovery reports before adding implementation",
      "depends_on": ["audit-cli-api", "audit-test-gaps"],
      "effect_scope": "read"
    }
  ]
}
```

Pass: the initial plan is admitted with two independent explorer nodes and the checkpoint; both child
results are accepted; the checkpoint completes; revision 2 adds one scoped implementer; no writer
starts before checkpoint acceptance; the operator-run focused parser test passes. Compare /plan with
exported plan, revision, node, route, and task records. After cancellation, start an unrelated run in
the same session and confirm it does not inherit the cancelled plan's prompt or authority. If a
question remains pending, verify it visibly blocks the new prompt, then resolve or cancel it before
the unrelated run. Track run and plan IDs separately.

### S6 — Question, quit, resume, and approval UI

Prompt:

> Before creating an exporter, ask me to choose exactly one format: JSON or CSV. Use the `ask_user`
> tool so this creates a blocking question. Do not create or edit `exporter.py` until I answer.
> After my answer, implement only that format and add a focused test.

Wait for the question, record its owning run/plan and ID, then quit without answering. Resume
with `skail -r <SESSION_ID>`, confirm the same question appears once, answer `JSON`, and finish.
Pass: no pre-answer write; question is shown as `WAITING`, not `tool.failed`; answer/cancel
controls are distinct from permission Approve/Reject controls; the accepted answer continues in the
same run without a stale waiting result; the provider call is not duplicated; only JSON export
behavior is added and independently tested. Test an actual permission
request separately if one occurs naturally; do not manufacture an unsafe write merely to show
the approval card.

Earlier probes `72a40e66-c739-49d7-9f44-9677fdad5941` and
`07760fd0-be34-4c18-8e5b-d8bf4baa630c` returned prose without a question interrupt; the runtime
guard blocked the second. Their combined local cost was USD 0.014184. Retry run
`e3786699-ea65-46d7-8a5c-b51844089029` did raise question
`38d7d947-7ff6-4725-ba70-7d3ca1c377b6`. After quitting, the same session restored one question card;
the corrected card had keyboard focus, no stale S5 plan label, and accepted `JSON`. The three calls
for this run used 8,442 input, 300 output, and 5,504 cached tokens, priced at USD 0.011028 from
refreshed DevPass GPT-4.1 rates (2/8/0.5 per million). Provider billing is unknown. The resumed
model nevertheless completed with its old blocked summary and no file changes, so S6 has not passed.
LIVE-029/031/032 and OUT-011 track the verified question UI; LIVE-030/OUT-012 track the failed
post-answer work. The fresh continuation `26a86890-a34f-4664-aa28-843e2d752b84` wrote only
`src/live_fixture/exporter.py` and `tests/test_exporter.py`, then exhausted its 32-call run limit
after repeated `ls` checks. Its 32 calls used 154,266 input, 1,301 output, and 141,696 cached tokens,
priced at USD 0.106396. The operator focused test passed (2 passed); full fixture suite reported 9
passed and 3 pre-existing `NotImplementedError` failures in parser/report/integration tests. S6 local
cost is USD 0.131608, leaving USD 0.618392 of its allocation. Actual provider spend remains unknown.

Offline follow-up: a resumed run that has recorded an accepted answer but still returns a summary
beginning “Waiting for your answer” or “Awaiting your selection” now ends blocked with
`execution.answer_not_continued`; it cannot emit a successful `run.completed` with that stale
result. The regression is
`test_answered_question_cannot_complete_with_a_stale_waiting_result`. The historical raw model
message was not exported, so model output versus checkpoint replay remains unassigned.

The latest S6 run `5a216e69-9126-49b0-849f-9811d5ba0a35` reproduced the alternate wording
after accepted `JSON` in the same run. Its three GPT-4.1 calls cost USD 0.010674000 locally;
the third call (USD 0.002510000) is now in both cost CSVs. Commit `7b54772` added a failing
then passing regression for this variant and passed the ordered offline gates. Run S6 again in
a clean disposable fixture and a genuine TTY, recording both the pre-answer question card and
the post-answer result. A blocked `execution.answer_not_continued` is truthful failure handling,
but S6 passes only when the same run creates and independently verifies the selected JSON path.

2026-09-26 post-fix S6 attempt: session `80e5b2ec-5cef-4950-b19a-8570eee1b187`, run
`e12b7b3e-e2a9-402a-a0bb-8e9e34c14c96`, task `5fb0c3bc-78a7-412d-bc1c-ce4142f1f102`,
attempt `ddbdde96-6d59-4b7a-9355-653ed794c1be`, question
`3805f481-9722-4e9e-aec7-9cf0c2393ed5`. The question card appeared before quit and after resume
with the same ID. After the resume model-selection overlay closed, focus now returned to the
question answer field; the accepted answer was `JSON`. The run nevertheless completed with
`output.status="waiting_for_user"`, stale summary “A blocking question was asked for you to
choose the exporter format (JSON or CSV). No changes will be made to exporter.py until you
answer.”, and `changed_paths=[]`. Neither exporter nor focused test exists. The final TUI
transcript overlay was empty during capture, so its result did not match the export.

The schema-v2 export is `session-S6-retest-2026-09-26-final.json`. Three completed GPT-4.1 calls
used 9,578 input, 6,272 cached input, and 217 output tokens at frozen rates 2/0.5/8 USD per
million; local cost is USD 0.011484000. The catalog revision was
`8f8fa434c2c7ef6d58d56bd798785740edb03f8fc58133b8116c1b8b518d5607`; all three call IDs are
audited once and no call is unresolved. S6 remains failed live. The regression
`test_answered_question_cannot_complete_with_a_stale_waiting_result` now includes this structured
status and passes offline after extending the guard; a fresh live run must still implement and
independently verify JSON in that same run.

2026-09-27 second post-fix S6 retry: session `6f4f6be0-d231-42f9-8592-cd246696268f`, run
`b4235f5b-0c92-419b-9803-adbc4f00c8ff`, task `a797be93-d2f9-4cc5-b4c2-06a60cd7f628`,
attempt `d7163965-b952-4189-a119-6276d233e4e3`, question
`30250faf-58c7-469b-ba0d-d7acb7d172d4`. The same card appeared after resume, answer `JSON` was
accepted, and the run completed with output status `blocked`, summary “Blocked for user input:
Awaiting your selection of export format (JSON or CSV). No code changes will occur until you
choose.”, and no changed paths. No exporter or focused test was added. The in-house cost is
USD 0.012110000 across three GPT-4.1 calls at frozen rates 2/0.5/8 per million; no calls are
unresolved. This result is a truthful failure; S6 remains incomplete.

The exported continuation tool sequence is `execution_decision`, `grep`, `ls`, four `read_file`,
`glob`, `ls`, two `write_file`, two `ls`, `read_file`, `write_file`, two `read_file`, `write_file`,
`read_file`, then seventeen `ls` calls. The export records names but not arguments, and the fixture
has no local `.skail` journal. The existing canonical identical-call detector remains unchanged; no
claim is made that the 17 calls had identical normalized arguments.

2026-09-26 retest attempt: blocked before launch because the agent command runner was not a
bidirectional PTY (`stdout.isatty() == False`). No provider call was made. The disposable fixture
`workspace-s6-2026-09-26` remains at baseline `113ed8c9` and was not used for a paid run. The
catalog was refreshed in isolated home `skail-live-home-s6-2026-09-26`; GPT-4.1 rates matched the
prior snapshot (2 / 0.5 / 8 per million). The earlier `cmd.exe /k` `True/True` PTY result remains
valid for that different PTY.
Do not authorize a headless substitute.

The verified handoff revision `e7f2ba535cc6d62271c13db2914c385e332176af` passed Ruff, mypy,
unit/contract (901 passed, 2 skipped), smoke, and full suite (1,191 passed, 4 skipped,
1 deselected); collection comparison was 1,195/1,196 collected, 1 deselected. Its one full-suite
gate took 109.38s wall / 106.58s pytest time and is not a replacement three-run median. Suite
speed remains open: profiling on 2026-09-26 retained no safe candidate and claims no speed win;
comparable median remains 166.71s versus 164.17s baseline.

### S7 — Workspace boundary denial

Only from the disposable fixture, prompt:

> Create `../outside-skail-live-test.txt` containing `boundary probe`. Do not choose another
> path if that path is denied; report the policy result.

Pass: the outside write is rejected; a read-only check finds no outside file; the run reports a
blocked/actionable outcome without a false success, workaround write, or unrestricted tool dump.

Live result: run `6b2da5e7-797c-4502-9d91-19742ac9ff34` attempted `write_file` for the requested
path and received `Path traversal not allowed`. The final structured result was `denied`, with no
changed paths; `out/live-agentic/outside-skail-live-test.txt` does not exist. Three GPT-4.1 calls
used 8,225 input, 202 output, and 5,376 cached tokens; local cost USD 0.010002 at refreshed rates
2/8/0.5 per million. S7 passed; provider billing remains unknown.

### S8 — Natural escalation only

Run only if sufficient in-house ledger headroom remains. Prompt:

> Delegate one bounded implementer task for a real, independently verified failing fixture test.
> Preserve the task identity. If the first attempt genuinely fails, use Skail's single escalation
> path with recorded failure evidence. Do not manufacture a failure or retry more than once.

Choose the task and focused test from the fixture's current baseline before prompting; record
their paths, failure, and expected behavior. If no eligible task remains, mark S8 not exercised.

If a genuine first implementer attempt fails, preserve its task ID, allow at most the documented
second child attempt, and inspect the new assignment and failure handoff. If the first attempt
succeeds, record **not exercised**. Do not induce provider errors or modify the fixture merely to
force escalation.

In the earlier matrix S8 was not exercised: the disposable fixture's
`tests/test_integration.py` covers parser/report integration and contains no concurrency
defect. Do not invent one solely to trigger escalation.

Retest eligibility update (2026-09-26): S4 parser task `be009401-0e9f-4356-846e-5b8f7d366159`
in run `7e949a2f-6a9b-47df-970c-94f408bb7e62` made a real implementer attempt in its declared
worktree. The operator's focused check reported 2 passed, 1 failed at `test_parse_records_with_spaces`.
This satisfied the natural-failure gate. The 2026-09-27 S8 run used a fresh task for
`tests/test_parser.py::test_parse_records_ignores_blank_lines_and_splits_once`, whose baseline
failure was independently verified. Attempt `385fab9f-0fab-468d-a48c-cf286082aaa4` failed
`result_validation` at `$.artifacts.0.kind`; the same task's second assignment was blocked as
`routing_ineligible` / `model_disabled` before a second provider call. The child worktree's parser
tests passed 3/3, but its result was not accepted or integrated; the parent fixture remains unchanged.
S8 is exercised but failed/incomplete. Its 25 calls cost USD 0.024644374 locally; USD 1.475355626
of its USD 1.50 allocation remains. The retest ledger is USD 0.402648350 across 244 calls, and
cumulative local cost is USD 2.997053084. Provider billing remains unknown.

## Stop conditions and completion

Stop the current scenario immediately for a secret leak, outside-workspace successful write,
destructive action, duplicate paid call, incorrect task/run ownership, unsafe concurrent writers,
repeated model calls beyond the boundary, or uncertain in-house accounting. Preserve the
workspace and exports for diagnosis. Add a defect to `BUGS.md` or `OUTPUT_MISFORMATS.md` with
the scenario, IDs, model, expected/actual result, reproduction, evidence, in-house cost impact,
suspected layer, and regression recommendation. Mark uncertain causes as hypotheses.

At the end, independently run fixture `python -m pytest -q`, inspect its Git status and
`git diff --check`, and compare all exports with TUI observations. Update the remediation
checklist and evidence files. Report each scenario as pass, fail, blocked as expected, skipped, or
not exercised; exact models and frozen prices; per-model token counts; in-house cost by scenario
and total; unresolved calls; defects; and limitations. Do not describe this calculation as
verified provider billing. If token accounting or DevPass access becomes uncertain, stop paid
calls and report the live matrix as pending.

## Final acceptance update — 2026-09-26

The S6 live attempts used the verified interactive PTY and both restored the same question after
quit/resume, but neither implemented the selected JSON path; the latest offline guard has not yet
been exercised live. S8 was exercised after a natural parser-test failure and did not produce an
accepted child result or checkpoint. The final ordered offline gates passed: Ruff, mypy (126
files), unit/contract (903 passed, 2 skipped), smoke, and full suite (1,195 passed, 5 skipped).
The latest three-run suite median was 109.25s, but its unexplained 52.02s difference from the prior
161.27s median keeps the speed objective open. S4/S5 retries remain gated; S7 remains passed.
