# Defect remediation, offline suite, and live validation plan

Status as of 2026-09-26: the latest behavioral repair is `7b54772`, which blocks the observed S6
"Awaiting your selection" stale summary after an accepted answer. Its recorded ordered offline
gates passed (Ruff, mypy, unit/contract 900 passed and 2 skipped, smoke). The recorded full-suite
count was 1,184 passed and 5 skipped; a fresh audit run of `rtk pytest -q` passed 1,189 with
5 skipped. The count difference is unresolved and needs a collection comparison in the next
timing pass.
S1 and S3 passed their applicable retests; S2's corrected focused test passed, but its final TUI
text was not captured. S4 remains failed after bounded live attempts: no child TaskResult was
accepted and no checkpoint or FIFO follow-up completed. Its scope fix is verified offline, while
direct live denial remains unobserved. S5 is withheld pending diagnosis. S6 needs a same-run live
retest after the repair; S8 is eligible after a natural parser test failure. The 20% offline suite
speed target remains unmet. See [the checklist](defect-remediation-todo.md) for individual defects.

The latest complete retest export exposed 16 previously unlogged S4 calls (USD 0.019030400) and
one S6 continuation call (USD 0.002510000). All 213 retest call IDs now occur once in
`CALL_COST_AUDIT.csv`; its USD 0.354409976 sum matches exported model usage. Adding the historical
USD 2.594404734 gives a USD 2.948814710 cumulative in-house stop total, with USD 5.551185290
to the USD 8.50 normal stop and USD 7.051185290 to the USD 10 ceiling. Actual provider billing
remains unknown. A `cmd.exe /k` PTY in this environment returned `stdin=True, stdout=True` from
Python; the earlier non-TTY observation applied to a different shell invocation. No new paid run
was made during this audit.

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
Live S8 remains unrun. The ledger reconciliation is complete and a bidirectional `cmd.exe /k`
PTY was verified in this environment. A new live run still requires a clean disposable fixture,
isolated home, current DevPass qualification, and the scenario's offline gates. The earlier TTY
failure remains historical evidence for that launch path.

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
   distinct qualified route before a paid retry. Record cause as unknown until proved.
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

## Documentation and delivery gate

Keep README, SPEC, FEATURES, ARCHITECTURE, CLI, EVALUATION, PERFORMANCE, THREAT_MODEL,
DEPENDENCIES, relevant ADRs, this plan, the checklist, and the live plan consistent with
verified contracts. Historical ADR decisions remain visible with explicit supersession notes.
Check local links and commands. Do not turn unconfirmed hypotheses into product claims.
Commit coherent behavior, test-suite, and documentation changes with Conventional Commit
messages; preserve pre-existing worktree changes. The final report separates **fixed and
verified offline**, **confirmed live**, **still open**, and **external billing unknown**.
