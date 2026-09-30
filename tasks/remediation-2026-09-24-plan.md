# Defect remediation, offline suite, and live validation plan

> The current implementation handoff is [the remaining remediation plan](plan.md), with its
> [execution checklist](todo.md). It diagnoses the outstanding paths at `9f9d1c9` and supersedes
> the prospective execution order and older balances below. Preserve these dated records as
> evidence; the 2026-09-28 implementation progress and remaining live gaps are recorded in plan.md and todo.md.

## Current acceptance status (2026-09-27; reconciled)

| Scenario | Current status | Acceptance evidence / remaining gap |
|---|---|---|
| S1 | Passed for the earlier live read-only answer | The historical export did not retain the final message; do not claim a current TUI/export presentation match. |
| S2 | Implementation/focused check passed; presentation open | Operator focused test passed 4/4. Final TUI/export answer comparison was not captured. |
| S3 | Read-only checks passed; presentation open | Requested model routing was observed; final rendered TUI/export text comparison was not captured. |
| S4 | Failed/incomplete live | No accepted child result, checkpoint, or FIFO follow-up. Offline planned child-scope denial passes; direct live child denial remains unobserved. |
| S5 | Withheld | Historical explorer failure cause remains unknown; no accepted discoveries/checkpoint/revision. |
| S6 | Failed live | `out/live-agentic/s6-retest-20260927T140000Z/session-export-schema-v2.json` has `run.completed`/succeeded task despite two `decision.plan_invalid` errors (`effect_scope: invalid_type`); no model-written exporter or focused test. The operator-edited fixture is quarantined. This is an S6 acceptance false-positive, not evidence by itself of a global lifecycle-contract defect. Offline enum/type diagnostics and the mounted Ctrl+C/resume test are not live acceptance. |
| S7 | Passed for lead workspace traversal denial | The lead's outside write was denied. Offline child-scope test passes, but live child-scope denial was not exercised. |
| S8 | Exercised; failed/incomplete | Natural first attempt failed result validation; sole retry was ineligible (`model_disabled`) before provider execution. Synthetic offline eligibility tests do not establish live eligibility or close S8. |

The ordered offline gates passed on the current code tree (`e9779f6`; documentation-only edits were
present): Ruff, strict mypy (126 files), unit/contract **916 passed, 2 skipped**, smoke, and full
suite **1,213 passed, 5 skipped**. These gates are not a release verification. A separate
clean-HEAD timing record on `0d916ab` reports a **201.816 s external-wall median** (three runs);
the 20% wall-time target remains open, and this timing is not measured on the current HEAD. The
local in-house token-derived campaign total is **USD 3.019357484**, excluding historical unknown
costs and unattributed provider observations; it is not provider billing. Preserve ignored evidence
and dated entries unchanged.

Status as of 2026-09-26: verified handoff change `e7f2ba535cc6d62271c13db2914c385e332176af`
adds allowlisted `failure_category` and schema-shaped `validation_path` to attempt-two failure
handoff when recorded; raw child output is not copied. Its offline gates passed: Ruff, mypy,
unit/contract 901 passed and 2 skipped, smoke passed, and full suite 1,191 passed, 4 skipped,
1 deselected. The full-suite run took 109.38s wall / 106.58s pytest time. The collection comparison
reported 1,195/1,196 collected and 1 deselected. This is one gate run, not a three-run median; do
not infer a cause for historical count differences (earlier notes of 1,184/1,185/1,189 are from
prior revisions).
S1 and S3 passed their applicable retests; S2's corrected focused test passed, but its final TUI
text was not captured. S4 remains failed after bounded live attempts: no child TaskResult was
accepted and no checkpoint or FIFO follow-up completed. Its scope fix is verified offline, while
direct live denial remains unobserved. S5 is withheld pending diagnosis. Two post-fix S6 same-run
retries accepted `JSON` but neither produced the exporter: one completed with output status
`waiting_for_user`, and the next emitted `run.completed` with output status `blocked` and a stale
waiting summary. The structured-status guard
is fixed offline; S6 remains failed and further paid retries need a distinct corrective route.
S8 was exercised after the natural parser test failure; its first child result failed validation
and its single retry route was blocked before a provider call, leaving no accepted result. S8 remains
incomplete. The 20% offline suite
speed target remains unmet. See [the checklist](defect-remediation-todo.md) for individual defects.

Offline S4 scope evidence (2026-09-27): an integration test now exercises the planned resource scope
through request construction, task validation, and the assembled child agent's actual filesystem
tool. Its scripted out-of-scope write is denied and leaves no outside file. The focused test passed;
this confirms the exercised offline boundary and adds no source fix. It is not direct live child
denial evidence; that retest remains unobserved.

The 2026-09-26 offline S4 diagnosis found that the preserved export records the expected rejection
categories and contains no raw child output; the attempt-two handoff now includes a safe
`validation_path`, and its focused regression passes. This does not establish a runtime acceptance
bug or justify another paid S4 attempt; S4 remains failed live. S5's cause remains unknown, and S5
remains withheld with no paid retry.

At the prior cost checkpoint, the complete retest export contained 213 audited calls costing
USD 0.354409976 in-house, and cumulative local cost was USD 2.948814710. The earlier command-runner
PTY block remains historical; a verified interactive `cmd.exe /k` route was subsequently used.
Actual provider billing remains unknown. The 2026-09-27 retry update is recorded below.

## Evidence baseline and rules

The source of truth for observations is `out/live-agentic/BUGS.md`,
`OUTPUT_MISFORMATS.md`, `RUN_LOG.md`, `COSTS.csv`, and the redacted schema-v2 session exports.
Those files are ignored by Git; keep them in place and cite run, task, attempt, plan, question,
and provider-call IDs when changing an entry. The historical USD 0.4376813 figure was exported
usage plus estimates, not verified provider spend. The S5 plan in run
`46335ece-a442-4a0b-bb14-19f220c73846` and the S4 retry conflict question in run
`ea102525-dc0f-412d-92f4-deddf12b6458` are separate events. Queue persistence over restart
has not been demonstrated; do not attribute the question to it.

The user-authorized historical campaign stop remains **USD 2.594404734**. Independent per-call
recalculation priced 296 current-campaign calls at USD 1.803778734; ten calls lack token usage and
are conservatively settled at USD 0.783784. A USD 0.006842 carry-forward buffer preserves the
previously stated cumulative stop after correcting one duplicated scenario row in `COSTS.csv`.
Actual provider charges are unknown. `out/live-agentic/CALL_COST_AUDIT.csv` records the local
recalculation for every call in seven latest schema-v2 session exports. Sixteen older measured calls
reprice to USD 0.173399080 in-house; six older calls have no token counts. Those earlier exported
amounts remain outside the current campaign ledger and are not provider billing evidence. Do not
use the in-house ledger as provider billing evidence or replay an ambiguous assignment. The final
three full-suite runs passed **1,185 tests, 5 skipped** in a median **166.71 seconds wall time**
(163.01 seconds pytest time) on Windows 11 with Python 3.14.6. Unit/contract passed 900 with 2
skipped; Ruff, mypy, and smoke passed. Compared with the measured 164.17-second baseline median,
the full suite is 1.5% slower while adding nine passing regressions. Bottleneck-specific gains and
the measured slices are recorded in the checklist and `docs/skail/PERFORMANCE.md`.

Preserve the existing worktree, including the user's uncommitted README edits. For each behavior
change: write a failing deterministic regression, implement the smallest fix, run focused tests,
update its contract or ADR if the public behavior changes, then run the complete offline gates.
Record failure codes and observable events; do not infer a root cause from a missing provider
error. A live outcome closes a defect only when the TUI, export, and workspace agree.

## Phase 1 — Reconcile and triage every issue

1. Keep the crosswalk current for LIVE-001–038 and OUT-001–014 using exact exports and
   current source tests. Label each **open**, **fixed offline/live unconfirmed**, **confirmed live**,
   **test-plan mismatch**, or **provider outcome unknown**. Check missing and stale statuses
   against the latest runs; retain original observations.
2. Independently recalculate each schema-v2 provider call using frozen model rates and input,
   cached-input, and output tokens. Sum children into the owning run/session, compare with
   `COSTS.csv` and exported `model_usage`. Compare the latest complete session's call-ID set
   with `CALL_COST_AUDIT.csv` before another paid call. Keep measured and estimated charges separate.
   Reconcile interrupted calls conservatively before any new paid call. Provider spend remains
   unknown unless independently observed; the user authorized proceeding without that evidence.
3. For each open issue, save the smallest redacted reproducer, expected event sequence, actual
   output, workspace diff, severity, and test owner. Distinguish model-authored bad content from
   runtime acceptance, presentation, or provider transport defects. Update the registries as
   evidence changes, not simply because a focused test passes.

**Exit:** no entry is dropped, all cost rows and call IDs reconcile locally, and uncertain causes
are marked as hypotheses. The current 213-call retest export meets the cost reconciliation check.

## Phase 2 — Repair runtime defects in dependency order

### 2.1 Execution intent, plan admission, and claimed work

Cover LIVE-002/012/013/016/019/026/027/028 and OUT-009/010. Recheck existing direct,
no-write, exact child count, named profile, and explicit planned-mode guards with scripted lead
responses at first execution and resume. Add a regression in which a model says children launched
despite no admitted plan; completion must block with `execution.intent_not_satisfied`, no tasks
or writes. For malformed plan payloads, improve the schema/example or field-specific rejection
only after comparing attempted tool arguments with the plan schema. A rejected plan may consume
one bounded repair; it must never become a successful planned run. Preserve immutable assignment
and child ownership.

### 2.2 Child results and adaptive checkpoint

LIVE-024 is the main S5 blocker. The latest export confirms both admitted GPT-4.1 explorer tasks
failed before accepted results; it contains no child result, failure category, or validation path,
so the cause remains unknown. New events now record a safe failure category and schema field path
for provider errors, malformed results, result validation, route ineligibility, budget blocks, and
task failures. Scripted child regressions verify those diagnostics without raw output or secrets.
The historical cause cannot be reconstructed from the export. Do not pay for an S5 retry until an
eligible route or other offline evidence establishes a cause and corrective action.

#### 2026-09-26 diagnosis

**Observed — S4:** Preserved export `session-S4-qwen-final.json` for run
`9652cfc8-bd46-4195-81e8-1419efd41ef1` records parser task
`19f3f5d0-fe75-48e6-a0f7-4063ab40a832` failed with `failure_category` `result_validation` and
`validation_path` `$.artifacts.0.kind`; report task
`9aecab0e-3e19-430d-8823-cc91834e59f8` failed with `malformed_result` at `$`. Raw child output
is absent. These categories match `parse_child_result` rejecting invalid model output; they do not
prove that the runtime rejected a schema-valid `TaskResult`. Child-worktree focused tests passed
(parser 1 passed, report 1 passed), but their results were not accepted: `run_controller` integrates
a changeset only when `result.status == succeeded`.

Existing contract tests already accept a valid schema `TaskResult` with artifact `kind`/`path` and
verification evidence for the fields those tests cover. The live export contains no valid result
that was dropped, so a new regression was not needed to establish that valid results are accepted.
The runtime child contract (the `run_controller` Final TaskResult contract and context-packet
suffix) names `status`, `summary`, `artifacts`, and `verification`, and requires a valid
`evidence_ref` for write-capable work, but does not specify the artifact object shape
`{kind, path, digest}`. `response_schema="task_result"` is a routing label, not a JSON schema bound
to the provider call. The S4 operator prompt did specify `{kind, path}` and `evidence_ref` objects;
operator text is not the runtime child contract. This is a guidance gap consistent with the observed
validation path, not a demonstrated cause of the model output; raw output is absent.

The attempt-two handoff previously omitted `failure_category` and `validation_path`, despite
Architecture §10.3 requiring a concise failure code. A failing
`test_second_attempt_handoff_includes_safe_validation_path` regression was added; `bounded_handoff`
and `task_graph` now pass allowlisted categories and schema-shaped validation paths. Unknown
categories and unsafe paths are dropped, and raw output is not copied. Focused tests passed (9
passed across `tests/unit/test_escalation.py` and `tests/integration/test_task_escalation.py`);
Ruff and mypy passed on this revision. This handoff fix does not make S4 live-eligible by itself.
S4 remains failed live, and direct post-fix denied-write observation remains pending; scope fix
`d92b4b9` remains the offline denied-write repair. Do not pay for another S4 attempt until a fresh
fixture run is separately justified: the acceptance bug was not reproduced offline, and the handoff
fix is necessary but not sufficient for S4 pass criteria (two accepted implementer results,
checkpoint, disjoint scopes, and FIFO follow-up).

**Observed — S5:** Export `session-S5-final-retry-final.json` for run
`071ba5b0-5c91-479d-bb14-74db2e951997` records `task.failed` with `reason` null, no
`failure_category`, no `validation_path`, and no raw child result. The cause remains unknown. The new
handoff change does not reconstruct or fix the historical S5 failure. S5 stays withheld; no paid
S5 retry.

#### Offline S8 and result-acceptance follow-up

The current S8 export records a child `result_validation` failure at
`$.artifacts.0.kind`; its one retry assignment ended `model_disabled` before a provider call. The
natural parser test failure was not induced. This does not establish that a schema-valid result was
rejected, nor that the natural-escalation transition is defective: offline `TaskResult` contract
coverage accepts artifact `kind`, while routing intentionally blocks a disabled model. No specific
offline regression reproduces an acceptance or escalation defect, so no runtime/schema change is
justified. Keep S8 incomplete and do not weaken result validation. For any later offline
investigation, separately verify the exact model exclusion and eligible-candidate set rather than
equating `model_disabled` with a broken retry.

The separate S4 export observations remain: one child failed validation at
`$.artifacts.0.kind`, another was `malformed_result` at `$`, and neither includes raw output or a
schema-valid result dropped by the runtime. This is not evidence of a valid-result acceptance bug;
do not change the schema or infer the model's malformed content. The existing artifact-kind
contract tests cover valid `TaskResult` construction. S5 still has no raw result, category, or path,
so its cause remains unknown and no route/cause is inferred from S8.

The latest offline call-ID audit lists 572 unique IDs. All audited S4 (210), S6 (3), and S8 (25)
IDs are accounted; seven of the 142 S5 IDs are marked `missing_usage`. The cumulative in-house
estimate is USD 2.997053084; provider billing remains unknown. These reconciliations do not alter
the live outcomes or authorize another provider call. The earlier full-suite 161.27-second median
is external wall; the later 109.25-second median is pytest-reported and has no wall measurement.
They are not comparable metric boundaries and do not establish a performance cause or speedup.

### 2.3 Answer/resume and bounded loops

LIVE-030 and OUT-012 are fixed offline. After an accepted answer, a resumed final result beginning
"Waiting for your answer" or "Awaiting your selection" now ends blocked with
`execution.answer_not_continued`; it cannot emit a successful `run.completed`. Regressions reproduce
both stale-result variants, and a contract test proves the same run can write only the selected JSON
output and its focused test. The historical
model response was not exported, so model output versus checkpoint replay remains unknown. The S6
continuation's 32-call sequence was inspected: the export records tool names but not arguments and
the fixture has no local journal. Leave the existing repeated-call detector unchanged because the
evidence cannot establish whether calls evaded its normalized-signature check. Keep the 32-call
ceiling and require a same-run live retest before declaring S6 complete.

### 2.4 Run ownership, queue, cancellation, and UI

Recheck LIVE-003–008/010/014/017/018/029/031/032 and OUT-001/003–005/007/011.
Exercise cancelled plan → unrelated new run, quit with queued follow-up, pending-question
restart, accepted answer, and permission approval as separate state transitions. Assert session,
run, plan, and question IDs on the same card and export; no old plan authority, duplicate
dispatch, empty no-TTY run, unawaited coroutine, or cancellation traceback. Explicitly test
queue persistence across process restart before assigning it any cause. Keep Answer/Cancel
distinct from Approve/Reject, focused and visible at 80×24. Mark prior repairs closed only
after a matching live observation or a documented reason live coverage is unnecessary.

### 2.5 Clean output, tool behavior, and remaining classifications

For OUT-002, capture the raw model final and rendered answer in a fresh S1 run; determine
whether internal criterion/evidence prose came from the model or presenter. Keep structured
evidence in events, present one concise answer, and preserve ordinary technical prose.
For OUT-006, test both a free-form answer and fixed-choice question; align tool guidance so
the requested input matches allowed choices, without weakening choice validation. Recheck
LIVE-011/OUT-008 with UTF-8 on Windows. Confirm LIVE-001 current catalog/price state before
automatic hard-budget routing; keep missing prices unavailable. Treat LIVE-009/015/023 as
documented scenario or projection outcomes unless new evidence contradicts them. Keep
LIVE-021/022/025 provider failures unresolved at call level and never replay those assignments.

**Exit:** each changed behavior has a red/green regression and stable terminal/event semantics;
the issue crosswalk records confirmed, unresolved external, and newly discovered defects.

## Phase 3 — Condense the offline suite without weakening it

1. Baseline and after measurements are complete. The baseline median is 164.17s wall / 160.82s
   pytest time for 1,176 passed and 5 skipped; the after median is 166.71s wall / 163.01s pytest
   time for 1,185 passed and 5 skipped. Baseline and after slices and slow-test purposes are in
   the checklist. Do not use test count alone as coverage.
2. Write a coverage map for every distinct mechanism: provider normalization and accounting,
   budget reservation, task/plan ownership, concurrency/leases, trust/path/secret boundaries,
   checkpoints/resume, CLI subprocess behavior, Textual mounted behavior, wheel contents,
   deterministic evaluations, and release scripts. Mark the test level that gives independent
   evidence for each. Keep actual wheel, subprocess, mounted TUI, cross-platform, and end-to-end
   checks where their boundary is the subject of the test.
3. Measured bottlenecks were optimized one at a time. Direct/module help fell from 15.84s to
   0.62s; removed-alias subprocesses fell from 8.96s to 0.87s plus in-process parser checks; the
   parallel evaluation fixture fell from 5.09s to 3.50s; real-wheel inspection fell from 6.02s to
   5.19s. The isolated no-credential subprocess and mounted keyboard, focus, queue, and resume
   pilots remain. The 20% total-suite reduction target was not met: additional independent-boundary
   coverage cost more time than the targeted savings.
4. CI duplication was removed: `ci.yml` retains the Windows/Linux Python 3.12–3.14 fast matrix
   and stable aggregate check, while `release.yml` runs on tags or manual dispatch. Ruff covers
   `evals` in both. [ADR 0010](../docs/decisions/0010-separate-fast-pr-and-release-gates.md)
   records the required-check migration; hosting branch protection remains an external check.
5. After every optimization, run affected focused tests and compare duration. At the end run
   Ruff, strict mypy, unit/contract, smoke, and full offline suite in repository order on
   the same environment; retain or restore tests if a mechanism or failure detection is lost.
   The first pass missed the ≥20% median wall-time target. Re-profile the current suite after the
   added regressions, identify setup that can be shared without hiding process, artifact, or
   mounted-TUI boundaries, and measure a second serial before/after comparison. Keep tests
   deterministic, isolated, and provider-free; report a smaller gain or no gain honestly if
   no safe consolidation meets the target.

**Exit:** all mapped mechanisms remain exercised, gate counts/statuses are understood, and a
repeatable before/after comparison shows a faster suite or documents why measured safe candidates
cannot achieve it. This exit is still open after the first pass.

## Phase 4 — Live plan repair and controlled rerun

Before a paid call, refresh the disposable fixture from a clean committed baseline, verify its
known failing tests, authenticate DevPass without printing credentials, freeze exact canonical
model IDs and prices, and independently price every completed call. Reconfirm both TTY streams
in the operator-controlled launch. Continue the existing retest subledger of USD 0.354409976;
retain the USD 2.594404734 historical local total in the cumulative stop calculation. Current
headroom is USD 5.551185290 to the USD 8.50 normal stop and USD 7.051185290 to the USD 10
best-effort ceiling. The user waived an
independent provider billing baseline and hard cap for this exercise; actual charges remain
unknown. Aim below USD 10 in-house, normally stop at USD 8.50, and stop sooner when a scenario's
allocation or unsettled-call rule requires it. A local token ledger is an estimate of spend.

S1/S2/S3 have been exercised. Capture the missing S2 final TUI/export comparison only if a
bounded scenario repeat is justified; do not infer it from the export alone. S4 has used USD
0.263971288 of its USD 1.60 allocation, leaving USD 1.336028712, and is marked failed after
bounded attempts. Repair or prove the child-result acceptance cause offline before any new S4
paid attempt; keep exact two-child, disjoint-scope, checkpoint, FIFO, and independent integration
acceptance criteria. Do not spend on another S5 attempt while the historical explorer cause
remains unknown. The offline event diagnostics make a future failure observable but cannot
reconstruct the old cause; proceed only if offline evidence
establishes a corrective action or a distinct eligible route. If S5 later becomes eligible, use a
fresh plan and route and require accepted explorers, checkpoint, revision, and implementation. Run S6
from a clean no-exporter fixture, answer JSON in the **same run** after quit/resume, and verify
the focused test independently. Schema-v2 export `session-S6-question.json` confirms the same-run
defect: run `5a216e69-9126-49b0-849f-9811d5ba0a35` persisted accepted `JSON` before completing
with an “Awaiting your selection” stale summary. Its alternate wording now has a failing then
passing offline regression. Live confirmation remains pending. S7 already passed; repeat only if its
boundary changed.
S8 is eligible because S4 parser task `be009401-0e9f-4356-846e-5b8f7d366159` naturally failed
`test_parse_records_with_spaces` (2 passed, 1 failed). Use a fresh task for a baseline parser test,
preserve task identity, and permit at most the documented second attempt. Do not induce a failure.
Live S8 remains unrun. A bidirectional `cmd.exe /k` PTY was verified in an earlier invocation, but
the 2026-09-26 S6 retest was blocked before launch because this session's command runner was not a
bidirectional PTY (`stdout.isatty() == False`). The earlier `True/True` result remains valid for
its different terminal. No paid call was made; do not authorize a headless substitute. A new live
run still requires a clean disposable fixture, isolated home, current DevPass qualification, and
the scenario's offline gates.

After each scenario, export schema-v2 evidence, compare TUI, events, fixture diff, and
independent test result, then reconcile measured tokens and conservative estimates before the
next call. Stop immediately for unsafe write, secret leak, duplicate paid call, wrong ownership,
or unpriceable/unsettled call. Record new defect IDs and output malformats promptly. Finish with
fixture tests, Git status/diff check, issue-status update, and a report of exact models, scenario
outcomes, local cost, unknown provider billing, and remaining defects.

## Remaining execution order and acceptance

1. **Child-result diagnosis (S4/S5):** Use preserved exports and deterministic fake-provider
   children to separate invalid model JSON, `TaskResult` validation, route ineligibility, and
   runtime acceptance. For S4, prove a valid scoped child result reaches the checkpoint and
   identify why the observed invalid outputs persisted after guidance changes. For S5, the old
    exports cannot reveal the precise explorer cause; require a specific corrective action or a
    distinct qualified route before a paid retry. Record cause as unknown until proved. The
    2026-09-26 pass completed the S4 export diagnosis and handoff regression; S4 and S5 paid retries
    remain gated.
2. **Offline speed pass:** Re-profile the current suite by mechanism and slow fixture. Change
   one measured setup at a time, retaining an independent subprocess, real wheel, evaluation,
   security boundary, and mounted TUI check where each tests the boundary itself. Record three
   comparable serial full-suite wall times and test counts before/after. The task remains open
   until the suite is faster than the 164.17s baseline or measured safe candidates are exhausted
   and the shortfall is explicitly reported.
3. **Ordered gates:** After any behavior or test change, write a red/green regression, run focused
   tests, then Ruff, mypy, unit/contract, smoke, and full offline suite in that order. Update
   specs/ADRs and Graphify for source changes. Older gate results do not prove a newer revision.
4. **Live continuation:** Verify TTY and isolated fixture again, refresh DevPass catalog and
   freeze assigned model IDs/prices, then run S6 in one durable run across quit/resume. Require
   accepted JSON, no stale waiting completion, only scoped exporter/test files, and independent
   focused test success. Compare TUI, export, workspace diff, test result, and every call ID before
   proceeding. Exercise S8 only under its natural-failure rule; revisit S4/S5 only after item 1
   establishes a repair or eligible route. S7 needs no repeat unless its boundary changes.
5. **Closure:** Update the issue crosswalk and ignored evidence after each observation. Audit
   README, specs, feature contracts, architecture, CLI, evaluation/performance docs, ADRs, CI,
   and links for verified behavior. Commit coherent tracked changes with Conventional Commit
   messages; report remaining defects and unknown provider billing separately.

## 2026-09-26 handoff revision and audit update

Handoff commit `e7f2ba535cc6d62271c13db2914c385e332176af` passed Ruff, mypy, unit/contract
(901 passed, 2 skipped), smoke, and full suite (1,191 passed, 4 skipped, 1 deselected). The
collection comparison reported 1,195/1,196 collected, 1 deselected. This single full-suite gate
took 109.38s wall / 106.58s pytest time; it is not a replacement three-run median. Do not infer a
cause for historical counts from earlier revisions.

Suite speed was profiled on 2026-09-26. No safe candidate was retained without weakening wheel,
subprocess, evaluation, security, and mounted-TUI boundaries. The objective remains open and no
speed win is claimed. Comparable median remains 166.71s versus baseline 164.17s. Slowest test was
`tests/unit/test_packaging.py::test_wheel_contains_only_the_skail_runtime` at 4.54s.

The S6 live retest attempt was blocked before launch because this session's command runner is not a
bidirectional PTY (`stdout.isatty() == False`). The earlier `cmd.exe /k` `True/True` result remains
valid for its different PTY. No paid call was made and cumulative local cost remains USD
2.948814710; provider billing is unknown. Do not authorize a headless substitute. S4 paid retry is
still not justified; S5 remains withheld because its historical cause is unknown.

README, the product docs, ADRs, tasks, CI workflows, local links, and documented commands were
audited read-only. No verified README inaccuracy was found, so README remains unchanged. The public
v0.1.0 release endpoint returned 404, consistent with the Unreleased badge. The item 18 audit is
complete; verified behavior and documentation changes are recorded in Conventional Commit commits.

## Documentation and delivery gate

Keep README, SPEC, FEATURES, ARCHITECTURE, CLI, EVALUATION, PERFORMANCE, THREAT_MODEL,
DEPENDENCIES, relevant ADRs, this plan, the checklist, and the live plan consistent with
verified contracts. Historical ADR decisions remain visible with explicit supersession notes.
Check local links and commands. Do not turn unconfirmed hypotheses into product claims.
Commit coherent behavior, test-suite, and documentation changes with Conventional Commit
messages; preserve pre-existing worktree changes. The final report separates **fixed and
verified offline**, **confirmed live**, **still open**, and **external billing unknown**.

## 2026-09-26 S6 retest after stale-summary repair

The verified interactive PTY route completed S6 run `e12b7b3e-e2a9-402a-a0bb-8e9e34c14c96`
in session `80e5b2ec-5cef-4950-b19a-8570eee1b187`. The same question
`3805f481-9722-4e9e-aec7-9cf0c2393ed5` was restored after quit/resume; the accepted answer was
`JSON`. The run then completed with structured output status `waiting_for_user`, a stale
“A blocking question was asked...” summary, and no changed paths. No exporter or focused test
exists, and the independent fixture suite remains at its four seeded failures. S6 failed live.

The export `session-S6-retest-2026-09-26-final.json` contains three GPT-4.1 calls at frozen rates
2/0.5/8 USD per million, totaling USD 0.011484000 in-house. All three call IDs are audited once;
there are no unresolved calls. Retest subledger cost is USD 0.365893976 across 216 calls;
cumulative local cost is USD 2.960298710, leaving USD 5.539701290 to the USD 8.50 stop and
USD 7.039701290 to the USD 10 ceiling. S6 has used USD 0.153766 of its USD 0.75 allowance and
has USD 0.596234 remaining. Provider billing remains unknown.

A failing integration regression for the exported `waiting_for_user` result was added before the
runtime guard change. It now blocks with `execution.answer_not_continued`; focused coverage passes.
A fresh same-run live pass is still required. The TUI transcript overlay showed no final answer
during this attempt; preserve the schema-v2 export as the terminal result evidence.

## 2026-09-26 final offline suite profile

On Windows 11 / Python 3.14.6, three serial `python -m pytest -q --durations=40` runs on the
final behavior/test revision each collected 1,199 cases (1,194 passed, 5 skipped). Wall times were
162.76s, 146.77s, and 161.27s (161.27s median); pytest-reported times were 159.22s, 143.24s, and
157.70s (157.70s median). The wall median is 1.8% below the 164.17s baseline, but sample ranges
overlap, so no causal gain is claimed. The 20% target remains unmet; no safe boundary-preserving
setup sharing was identified. Per-run duration logs are
`out/live-agentic/offline-final-e9fdf6b-s6guard-durations-{1,2,3}-python-pytest.txt`.

## 2026-09-27 S6 retry2 outcome

Fresh session `6f4f6be0-d231-42f9-8592-cd246696268f` resumed run
`b4235f5b-0c92-419b-9803-adbc4f00c8ff`, restored question
`30250faf-58c7-469b-ba0d-d7acb7d172d4`, and accepted `JSON`. Its `run.completed` event carried
output status `blocked`, a stale waiting summary, and no changed paths. No exporter or test was
written; S6 remains failed under its acceptance criteria. The schema-v2 export is
`session-S6-retry-2026-09-26-final.json`.

The three GPT-4.1 calls cost USD 0.012110000 locally. All 219 retest call IDs are now audited
once at USD 0.378003976. Cumulative local cost is USD 2.972408710, leaving USD 5.527591290 to
the USD 8.50 stop and USD 7.027591290 to the USD 10 ceiling. S6 has used USD 0.165876 and has
USD 0.584124 remaining. Provider billing remains unknown.

## 2026-09-27 S8 natural escalation result

The existing S8 workspace `workspace-s8-2026-09-26` was clean at baseline
`113ed8c9f69b0b6dfca596b0dc86052d3b63dc3a`; the focused parser test failed naturally with
`NotImplementedError`. Session `58b8533a-d99b-4acd-bcc5-adcccd86a78a` ran `14913447-a527-452f-93b6-f83de65ce04b`,
plan `520b8cda-ded1-42bb-92ab-34ff1e80b8ce`, and implementer task
`f4dd996c-fb76-4914-8a2d-a11c42a248c7`. The first attempt failed TaskResult validation at
`$.artifacts.0.kind`; the same task's one second assignment was blocked as
`routing_ineligible` / `model_disabled` before provider execution. The child worktree passed its
focused parser tests (3 passed), but its result was not accepted or integrated. The parent fixture
remains unchanged. S8 is exercised but failed/incomplete.

All 25 completed calls are priced at USD 0.024644374 in-house. The retest ledger is USD 0.402648350
across 244 calls; cumulative local cost is USD 2.997053084, with USD 5.502946916 to the normal
USD 8.50 stop and USD 7.002946916 to the USD 10 ceiling. S8 has USD 1.475355626 left in its USD
1.50 allocation. Actual provider billing remains unknown.

## Final offline timing review

Three serial runs after the final blocked-result regression collected 1,200 cases each (1,195
passed, 5 skipped); pytest-reported times were 109.25s, 109.15s, and 111.52s (median 109.25s),
with no external-wall measurement. A fresh three-run serial measurement collected 1,201 tests each
(1,196 passed, 5 skipped, 5 warnings): external wall 159.466s, 173.378s, and 166.938s (median
166.938s); pytest-reported 156.010s, 169.850s, and 163.330s (median 163.330s). The earlier
161.27s median was external wall (its pytest median was 157.70s); comparing the later 109.25s
pytest median to the wall median was misleading. These records establish neither repeatable gain
nor a variance cause. Keep the 20% speed objective open. Raw fresh evidence:
`out/live-agentic/timing-20260927T055212Z/`; prior series remain under `out/live-agentic/`.

The final ordered offline gates on the working tree passed: Ruff, strict mypy (126 source files),
unit/contract (903 passed, 2 skipped), smoke, and full suite (1,195 passed, 5 skipped). The
accepted-answer regression passed all four stale-result variants. This does not change S6's live
status: both verified-PTY attempts failed the same-run JSON implementation criterion. S8 was
exercised under the natural-failure rule and failed/incomplete; S4 and S5 paid retries remain
withheld pending offline evidence.

## 2026-09-28 live continuation addendum

The current implementation status is maintained in [plan.md](plan.md), [todo.md](todo.md), and
[live-agentic-test-plan.md](live-agentic-test-plan.md); this dated record does not rewrite the
September 24–27 outcomes above. S4 subsequently passed live in session
`d59ee73b-4efc-4806-bb6b-ed157aaae0a5`: two accepted child results, completed evidence-only
checkpoint, 15.783365 seconds of observed child overlap, completed FIFO follow-up, and independent
parser/report/integration tests (3 passed). The separate direct live child-scope denial passed in run
`ae17ce6a-3a03-4f75-afc6-77f0c1381c8e`; this is distinct from S7's lead traversal denial. S6 passed
in attempt 10. S5 remains withheld because historical explorer failures lack sufficient cause
evidence; S8 remains failed/incomplete after its natural first-attempt result-validation failure and
ineligible retry. R9 active-child cancellation passed in session `b1afdf23-3f8e-48a7-bcd1-49bbdfb72c6f`,
run `2fdb4d2b-0a4b-4007-ac02-de0fb3f1b4d3`; both children were active, the FIFO prompt was visibly
discarded on cancellation, reservations settled/released, and no follow-up call or runtime warning
occurred. Conditional permission/question edges remain open. Presentation comparisons, the 20% suite-
speed objective, and hosted release/branch-protection evidence remain open.

Ordered offline gates and package-check passed on source commit `6a99a32`; clean-worktree
release-check passed on documentation candidate `4f0b342` with the same code. Later edits are
documentation-only and link-checked. The current append-only in-house campaign total is USD
`3.746818284`, with 821 unique call IDs audited once. Provider billing remains unknown. See
`out/live-agentic/RUN_LOG.md`, `COSTS.csv`, and `CALL_COST_AUDIT.csv` for the new live evidence and
reconciliation.
