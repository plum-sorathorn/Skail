# Defect remediation, offline suite, and live validation plan

Status: planned follow-up, 2026-09-24. The completed work and remaining checks are tracked in
[the checklist](defect-remediation-todo.md). The executable prompts, limits, and evidence fields
are in [the live test plan](live-agentic-test-plan.md). This plan makes no paid calls.

## Evidence baseline and rules

The source of truth for observations is `out/live-agentic/BUGS.md`,
`OUTPUT_MISFORMATS.md`, `RUN_LOG.md`, `COSTS.csv`, and the redacted schema-v2 session exports.
Those files are ignored by Git; keep them in place and cite run, task, attempt, plan, question,
and provider-call IDs when changing an entry. The historical USD 0.4376813 figure was exported
usage plus estimates, not verified provider spend. The S5 plan in run
`46335ece-a442-4a0b-bb14-19f220c73846` and the S4 retry conflict question in run
`ea102525-dc0f-412d-92f4-deddf12b6458` are separate events. Queue persistence over restart
has not been demonstrated; do not attribute the question to it.

The last recorded campaign local stop total is **USD 2.594404734**: USD 1.810620734 priced
from measured tokens and USD 0.783784 in conservative estimates. Ten calls remain unresolved
at call level but locally settled. Actual provider charges are unknown. Do not use the in-house
ledger as provider billing evidence or replay an ambiguous assignment. The latest full offline
suite passed **1176 tests, 5 skipped** in **158.88 seconds** on this Windows host; unit/contract
passed 892 with 2 skipped, and Ruff, mypy, and smoke passed. All future speed claims compare
the same suite, Python environment, and host with `pytest --durations` and wall time.

Preserve the existing worktree, including the user's uncommitted README edits. For each behavior
change: write a failing deterministic regression, implement the smallest fix, run focused tests,
update its contract or ADR if the public behavior changes, then run the complete offline gates.
Record failure codes and observable events; do not infer a root cause from a missing provider
error. A live outcome closes a defect only when the TUI, export, and workspace agree.

## Phase 1 — Reconcile and triage every issue

1. Build a crosswalk from all LIVE-001–032 and OUT-001–012 entries to exact exports and current
   source tests. Label each **open**, **fixed offline/live unconfirmed**, **confirmed live**,
   **test-plan mismatch**, or **provider outcome unknown**. Check missing and stale statuses
   against the latest runs; retain original observations.
2. Independently recalculate each schema-v2 provider call using frozen model rates and input,
   cached-input, and output tokens. Sum children into the owning run/session, compare with
   `COSTS.csv` and exported `model_usage`, and keep measured and estimated charges separate.
   Reconcile interrupted calls conservatively before any new paid call. Provider spend remains
   unknown unless independently observed; the user authorized proceeding without that evidence.
3. For each open issue, save the smallest redacted reproducer, expected event sequence, actual
   output, workspace diff, severity, and test owner. Distinguish model-authored bad content from
   runtime acceptance, presentation, or provider transport defects. Update the registries as
   evidence changes, not simply because a focused test passes.

**Exit:** no entry is dropped, all cost rows reconcile locally, and uncertain causes are marked
as hypotheses.

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

LIVE-024 is the main S5 blocker. Inspect redacted child events, route decisions, tool results,
and structured TaskResult validation for the four admitted GPT-4.1/Qwen explorer runs. Add
diagnostic event fields for a safe failure category and validation field path if the exports do
not distinguish provider error, malformed child result, routing ineligibility, and task failure.
Avoid raw model output or secrets. Reproduce the actual category with scripted child responses;
then repair the parser/guidance, route fallback, or failure handoff as evidence requires.
Test two accepted explorer reports, checkpoint completion, revision 2 adding one scoped writer,
and no writer before the checkpoint. Keep the two-attempt limit. Do not spend another S5 retry
until this category is diagnosable offline or a different eligible route is established.

### 2.3 Answer/resume and bounded loops

LIVE-030 and OUT-012 are open. Reproduce `user.answer=JSON` followed by a stale
“Waiting for your answer” final result using the same run-scoped checkpoint. Record the exact
resume input, model response, restored controls, and final-result source without exposing
secrets. If the model returned stale text, enforce that accepted answer and completed work
cannot finish as waiting; if checkpoint state replayed stale output, fix resume state/turn
ordering. Add a contract test proving the same run writes only the chosen format and a focused
test, then returns one truthful result. Investigate the S6 continuation's 32-call `ls`/read
sequence with normalized tool names/arguments; improve the existing repeated-call guard only
if the actual sequence evades it. Keep the run-wide 32-call ceiling and no paid call after it.
Do not declare S6 complete from a separate follow-up run.

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

1. Measure a baseline three times with `python -m pytest -q --durations=40`; record median
   wall time, test count, skips, and each slow test's purpose. The current one-run baseline is
   1176 passed, 5 skipped, 158.88 seconds. Measure unit/contract, integration, e2e, security,
   packaging, and mounted TUI slices separately. Do not use test count alone as coverage.
2. Write a coverage map for every distinct mechanism: provider normalization and accounting,
   budget reservation, task/plan ownership, concurrency/leases, trust/path/secret boundaries,
   checkpoints/resume, CLI subprocess behavior, Textual mounted behavior, wheel contents,
   deterministic evaluations, and release scripts. Mark the test level that gives independent
   evidence for each. Keep actual wheel, subprocess, mounted TUI, cross-platform, and end-to-end
   checks where their boundary is the subject of the test.
3. Optimize measured bottlenecks one at a time. The four direct/module `--help` subprocesses
   in `test_release_check.py` took 19.94s; inspect import startup and defer heavy eval/release
   imports on help, keeping all invocation contracts. The nine alias subprocesses in
   `test_cli_e2e.py` took 6.50s; test all aliases through the parser and retain representative
   external CLI invocation. The wheel integrity test took 5.41s; share a build artifact within
   the same gate where safe, while keeping real built-wheel inspection. Retain the isolated
   no-credential subprocess (4.98s). The parallel eval fixture took 4.56s; preserve observed
   overlap and output equivalence while reducing redundant policy setup only if identical work
   is still compared. Profile mounted TUI tests before moving purely static formatting checks
   to unit level; keep representative real keyboard, focus, queue, and resume pilots.
4. Review CI duplication: both `ci.yml` and `release.yml` run on PRs to `main`/`skail`, repeating
   Python 3.12 Windows/Linux unit/contract and smoke work. Propose a single required fast PR
   gate plus a full release gate using documented branch/tag policy, without removing Python
   3.12–3.14 or Windows/Linux coverage. Align Ruff's path set (`evals` differs today). Change
   workflows only with a coverage matrix and an explicit required-check migration.
5. After every optimization, run affected focused tests and compare duration. At the end run
   Ruff, strict mypy, unit/contract, smoke, and full offline suite in repository order on
   the same environment; retain or restore tests if a mechanism or failure detection is lost.
   Target a repeatable ≥20% median wall-time reduction; report actual result if the target
   cannot be met safely. Keep tests deterministic, isolated, and provider-free.

**Exit:** all mapped mechanisms remain exercised, gate counts/statuses are understood, and
the measured time improvement has a reproducible before/after record.

## Phase 4 — Live plan repair and controlled rerun

Before a paid call, refresh the disposable fixture from a clean committed baseline, verify its
known failing tests, authenticate DevPass without printing credentials, freeze exact canonical
model IDs and prices, and independently price every completed call. Use a **new subledger**
for the rerun while retaining the USD 2.594404734 historical local total in the cumulative
stop calculation. Thus USD 5.905595266 remains to the USD 8.50 normal stop and USD
7.405595266 to the USD 10 best-effort ceiling. The user waived an
independent provider billing baseline and hard cap for this exercise; actual charges remain
unknown. Aim below USD 10 in-house, normally stop at USD 8.50, and stop sooner when a scenario's
allocation or unsettled-call rule requires it. A local token ledger is an estimate of spend.

Run S1/S2/S3 first to confirm answer presentation, direct intent, model switching, UTF-8,
and bounded cancellation. Run S4 only with a fresh plan and disjoint writer scopes, exactly two
children, accepted results, FIFO follow-up, and operator-run integration test. The prior S4
allocation has only USD 0.087657256 left; a rerun may assign a fresh scenario allocation
before starting, but must record it against the cumulative headroom. Run S5 only after Phase
2.2, using a fresh
plan and route; require accepted explorers, checkpoint, revision, and implementation. Run S6
from a clean no-exporter fixture, answer JSON in the **same run** after quit/resume, and verify
the focused test independently. S7 already passed; repeat only if its boundary changed.
S8 is conditional on a genuine failed implementer attempt for an eligible fixture task; the
existing integration test has no concurrency defect, so remove that invalid prompt and never
manufacture a failure solely to exercise escalation. If no natural failure occurs, record
“not exercised.”

After each scenario, export schema-v2 evidence, compare TUI, events, fixture diff, and
independent test result, then reconcile measured tokens and conservative estimates before the
next call. Stop immediately for unsafe write, secret leak, duplicate paid call, wrong ownership,
or unpriceable/unsettled call. Record new defect IDs and output malformats promptly. Finish with
fixture tests, Git status/diff check, issue-status update, and a report of exact models, scenario
outcomes, local cost, unknown provider billing, and remaining defects.

## Documentation and delivery gate

Keep README, SPEC, FEATURES, ARCHITECTURE, CLI, EVALUATION, PERFORMANCE, THREAT_MODEL,
DEPENDENCIES, relevant ADRs, this plan, the checklist, and the live plan consistent with
verified contracts. Historical ADR decisions remain visible with explicit supersession notes.
Check local links and commands. Do not turn unconfirmed hypotheses into product claims.
Commit coherent behavior, test-suite, and documentation changes with Conventional Commit
messages; preserve pre-existing worktree changes. The final report separates **fixed and
verified offline**, **confirmed live**, **still open**, and **external billing unknown**.
