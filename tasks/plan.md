# Remaining remediation implementation plan

## 2026-10-03 post-commit disposition

This section supersedes the October 1 checkpoint status below. Commits `69acce1` and `28dcc28`
fix the clean-source identity mismatch and cancelled-provider-call accounting respectively. A live
selected-model `/quit` run and independent export replay confirm shutdown safety, an ambiguous
provider call, and a held reservation. The revised R10 accounting criterion permits a clearly
labelled local estimate when the provider response has no usage. `skail sessions reconcile-call
SESSION_ID CALL_ID` previews the greater of the frozen attempt estimate and completed calls'
locally priced observed token costs. `--apply` settles the held attempt only after each ambiguous
call is reconciled, while the cancelled call's tokens and provider charge remain unknown. No
additional paid retry is required to prove shutdown safety.

Commit `6b31278` removes an extra SQLite success-marker write from the normal measured-call path.
The returned response still receives a success marker when usage is absent or cannot be recorded;
unreturned calls remain ambiguous. A red/green regression covers the normal path. Ruff, strict
mypy, 995 unit/contract passes with two skips, smoke, and an optimized full suite of 1,307 passes
with five skips passed. The clean candidate package check passed and records the exact source,
wheel, and sdist hashes under `out/live-agentic/release-6b31278/`.

The clean `6b31278` release checker passed all eight stages, including the full offline suite,
benchmark thresholds, and fresh complete paired evaluation. The wheel SHA-256 is
`65f092f571cda276e59aa0bfb183e560aa9cc363a9b2887ed385e0e2d68c7542`; the sdist SHA-256 is
`92bb32b9b6d10975ea94f92d489914261438f7257147aa903b095e802d68b90b`. Its source digest
is `4ffde260c007fe26609405c620e3c0f7d59c497c3ee65ba7bb09c16fc9b307c6`.

Performance evidence and its limits are in [PERFORMANCE.md](../docs/skail/PERFORMANCE.md).
The suite speed target is retired as of 2026-10-03; runtime measurements are diagnostic and no
longer gate release. Before applying the new reconciliation command to historical sessions, the
R9 campaign had USD 1.96 in held reservations, USD 0.0602132 settled locally, and USD 0.9797868
remaining from the USD 3.00 cap. Its retained `/quit` export has one ambiguous GPT-5 mini call on
that assignment and a frozen attempt estimate of USD 0.017470. This is the read-only local estimate
for that call; the historical export and reservation were not modified. Held amounts are bounds,
not measured provider billing.
Hosted candidate CI, Python 3.12, branch protection, and provider billing remain unverified.

## Post-commit failure diagnosis and fixes (2026-10-01)

Checkpoint commit `be6fde9` contains the local remediation below. The user's README edit and the
untracked `tasks/latest_plan.md` were excluded from that commit.
This section supersedes the earlier 2026-10-01 R9 and release dispositions below.

- The published `8dcb932` Type check failure reproduced in a fresh Python 3.14 `.[dev]` install:
  mypy could not import `tomli_w` from `config/persistence.py`. The baseline did not declare the
  dependency. Fresh candidate installs pass strict mypy on Python 3.14 and 3.13 with `tomli-w`
  present. Evidence: `out/live-agentic/ci-typecheck-20261001/diagnosis-v2.json`. The hosted matrix
  still needs a run on a published candidate.
- The first clean `be6fde9` release check passed clean-tree, Ruff, and mypy gates, then failed one
  full-suite regression: `package_check.source_identity()` hashed an empty Git diff differently
  from the canonical evaluation identity. A clean-tree red/green regression and a one-line
  correction now make those hashes agree. The failed clean-candidate evidence remains under
  `out/live-agentic/release-be6fde9/`.
- Live composer `/quit` exposed a product accounting defect: `CancelledError` bypassed the model
  middleware's `Exception` handler; finalization relabelled its `started` provider call as
  successful without usage and settled the child attempt estimate. Calls now receive an explicit
  success marker only after the provider handler returns. Cancellation or unreturned calls become
  ambiguous and keep their reservations, while returned calls with missing usage still settle
  conservatively. Focused and mounted cancellation regressions pass; ADR 0008 records this boundary.
- The fresh live run in
  `out/live-agentic/r9-edges-20261001/runs/active-child-quit-accounting-fix/` observed a selected
  GPT-5 mini call active before `/quit`, a visible queued follow-up, one cancelled run, one cancelled
  child, no post-cancellation provider start, and unchanged files. The call is `ambiguous`, the
  child reservation remains held at USD 0.017470, and the separate USD 0.49 campaign reservation
  remains held. The original capture missed a transient shutdown-copy assertion; the independent
  replay verifies the visible queue, exact one-run count, and held accounting in
  `verification-replay.json` without another provider call.
- The USD 3.00 R9 campaign now has USD 0.0602132 settled locally, USD 1.96 reserved for attempts
  with unknown provider usage, and USD 0.9797868 remaining. Actual provider billing is unknown;
  the held reservation is a bounded accounting disposition, not a measured token cost. R9 shutdown
  safety is verified. R10 exact-cost acceptance stays open until the unknown provider outcomes can
  be reconciled. No further paid retry is needed to prove the safety behavior.

## Current implementation and verification (2026-10-01)

This section supersedes older prospective instructions and status summaries below where they differ.
Historical evidence remains preserved.

### Implemented in this continuation

- TOML persistence now uses declared `tomli-w`; nested model profiles, strings, unrelated settings,
  and atomic-save failure behavior have focused regressions.
- Approval callbacks are bound to the currently pending command request. IDs are stable across
  restore, reject cancellation is correlated, stale or malformed requests fail closed, and a valid
  one-shot approval is consumed before asynchronous resume. Approval-card focus now defaults to
  Reject; successful question cancellation restores focus to the composer.
- The TUI shell no longer imports DeepAgents/LangChain/LangGraph during module import. Its compact
  controls live in a lightweight module, and setup-only composer typing was removed from selected
  tests while real keyboard and focus interactions remain.
- `scripts/live_acceptance.py` is the maintained Windows PTY driver with fresh model-catalog and
  price qualification, selected-roster enforcement, isolated homes/workspaces, captured terminal
  frames, schema-v2 export verification, and a hard USD 3.00 append-only campaign ledger. The
  action-only answer flag now skips terminal-render comparison when no user-facing answer is part of
  the case; required presentation checks still compare the complete answer.
- Package artifacts now receive a source-and-hash `package-manifest.json`. Release verification
  rejects missing/stale manifests and modified wheel/sdist files. Release CI invokes each local gate
  through the release checker once and uploads the package directory, manifest, and release reports.
- `scripts/measure_suite.py` records collection IDs, source fingerprints (including untracked file
  hashes), interpreter/dependency versions, power scheme, raw output, and alternating serial
  baseline/candidate timings.

### Directed live R9 results

- Free-form question answer passed in `out/live-agentic/r9-edges-20261001/runs/question-freeform-retry/`
  (USD 0.0027128 locally). Question cancellation followed by unrelated fresh work passed in
  `.../question-cancel-fresh-run-final/` (USD 0.0025784).
- Allow-once planned command passed in
  `.../approval-allow-plan-only-verified/` (USD 0.0020160); rejected command passed in
  `.../approval-reject-plan-only-retry/` (USD 0.0019924). The first attempts remain unchanged and
  retained.
- One explorer completed the child-boundary task with no grandchild or workspace change. The saved
  child result reports `MINT GREEN` and that `task` is absent. The schema-v2 export passes the
  action-only replay verifier in
  `.../nested-boundary-direct-corrected/verification-replay.json` (USD 0.0092309). The original
  capture disposition records a terminal-answer mismatch; the case is operational evidence for the
  delegation boundary, not a user-visible presentation pass.
- Composer `/quit` observed an active selected child call, discarded the visible queued follow-up,
  and terminalized the run as cancelled with no fixture changes. Three retained attempts lack
  provider usage for a cancelled call, so USD 1.47 remains reserved and R9/R10 financial acceptance
  stays open for that edge. No further retry was made.
- Across this USD 3.00 R9 campaign, settled local token cost is USD 0.0602132, unresolved
  reservations are USD 1.47, and unallocated headroom is USD 1.4697868. Provider billing remains
  unknown. Failed and unresolved evidence was preserved.

### Performance and release disposition

The matched 2026-10-01 run used clean baseline `8dcb932` and the current candidate worktree, one
warm-up per tree, and three alternating pairs of the same serial pytest command. Baseline external
median was 123.309 seconds; candidate median was 123.508 seconds. The current candidate meets the
historical 131.336-second absolute target by 7.828 seconds. Paired changes were -0.669, +2.023, and
-0.904 seconds; with 1,305 candidate cases versus 1,257 baseline cases, this does not establish a
causal speed gain. There were 1,256 common node IDs; one differing ID is a randomized `uuid1()` test
parameter, and 48 actual cases were added. Evidence is in
`out/live-agentic/r11-matched-20261001/`; the historical 557b3fc 237.399-second median was not
reproduced and remains unexplained.

The current package build/install is verified separately. Its wheel SHA-256 is
`1e34d7670ab4e68bb4f44105daefaf335474243c995d956d343a52ba8847bb6a`; the sdist SHA-256 is
`c7ebf6bc179c2e2104c14bca869ba145d51ca88c47f332ab06449044b6d271f7`; the package manifest is
retained under `out/live-agentic/release-candidate-20261001-final/packages/`. A clean-worktree
release-check cannot be completed in this checkout because the candidate changes are uncommitted
and the pre-existing README edit must be preserved. Hosted Python/platform matrices and
branch-protection settings also remain external; no commit, push, dispatch, or protection change was
made. The latest public fast CI
run, #37 on commit `8dcb932`, failed with a visible `Type check` error in the six-job matrix and the
aggregate gate. Its job logs require GitHub authentication; an unauthenticated API request returned
403, while local mypy passes on both the baseline worktree and this candidate. The remote diagnostic
therefore remains unresolved. Branch-protection settings were not exposed unauthenticated. S8 remains
closed by the September 29 live resolution above.

## Presentation acceptance (2026-09-30)

Fresh real-TUI S1, S2, and two-model S3 runs completed; S1 and S3 left their fixtures unchanged.
S2 changed only the named normalization source/test, and independent focused tests passed 3/3
after the baseline failed. S6's retained completed run was resumed without a provider call to
capture its final answer. All five completion answers matched the current mounted Textual renderer
exactly and had answer fragments in saved terminal captures. Evidence:
`out/live-agentic/presentation-live-20260930/live-presentation-comparison.json`, scenario exports,
transcripts, and operator tests. The earlier historical export replay is retained at
`out/live-agentic/presentation-replay-20260930/`. One S3 first attempt blocked on missing decision
admission; one S2 attempt wrote `tests/__init__.py` outside scope and was cancelled. Both failed
attempts remain preserved. Thirty-two new unique fully priced provider calls cost USD 0.020565800
locally, including failed attempts. The append-only audit now has 925 unique IDs, zero duplicates;
the campaign estimate is USD 3.978118284. Provider billing is unknown. R10 presentation is closed;
conditional live R9 edges remain separate.

## Attempt diagnostics and offline gates (2026-09-30)

Attempt-keyed failure reason codes now survive retry terminalization and appear on their matching
session-export attempt rows. The export exposes only the bounded runtime category, excluding raw
provider output. Focused tests passed 21/21, including first-attempt failure followed by successful
retry. On the combined candidate, ordered gates passed: Ruff, strict mypy (126 files), unit/contract
941 passed and 2 skipped, smoke, full offline suite 1,252 passed and 5 skipped. The subsequent
exact-candidate package and release renewal is recorded below.

## Exact-candidate local release and speed evidence (2026-09-30)

Clean isolated commit `557b3fc2fe2338c948c8fada1bae541c595a20d9` matched the 26 changed
working-tree files by line content at snapshot time. Package build/install and all eight
release-check stages passed, including benchmark thresholds and a fresh paired evaluation.
Wheel SHA-256: `24962cb9b3f163206218a0c6e613f04ee960d006db041d9ede5cceddb5f59e08`;
sdist SHA-256: `2abb5989b87814f1c399ab62438fab40561647e34d924f9ed172c132b0ceb0e4`.
Retained package, benchmark, 54-fixture/2,700-result evaluation, and timing evidence:
`out/live-agentic/release-renewal-20260930/`. Three serial exact-candidate suite wall times were
238.548, 210.763, and 237.399 seconds, median 237.399. All 1,252 tests passed with 5 expected
skips in each run. The original 131.336-second target remains unmet; no safe causal optimization
was demonstrated. Hosted matrix and branch protection remain unverified because GitHub CLI has no
authentication here. The local release pass does not close those external or live presentation gates.

## S8 live pass (2026-09-29, current)

[S8 resolution](s8-resolution-2026-09-29.md): a real GPT-4.1 nano result-validation failure
escalated to selected GPT-5 mini on the same task, integrated, and passed the independent parser
test. Startup now honors the selected roster; retries require strictly greater persisted capability
fit. The run used reviewed user catalog profiles and fresh gateway pricing, not inferred model-name
quality. Sixteen run calls plus three latency probes cost USD 0.011183000 locally; campaign estimate
is USD 3.957552484. This closes R5/R10-S8 for the qualified run. Historical failures below remain
historical; other release and performance criteria remain open.

## S8 diagnosis update (2026-09-28, historical)

[The S8 diagnosis](s8-diagnosis-2026-09-28.md) found a genuine first child result-validation
failure and a retry blocked before provider execution. The exported `model_disabled` binding
can be dominated by disabled catalog entries; it does not prove enabled alternatives were disabled.
Fresh authenticated discovery found 143 accessible models and zero auto-eligible models. The
selector's binding explanation is repaired with a red/green regression, while routing admission
remains unchanged. S8 live acceptance requires trusted evidence for a distinct model above the
0.65 escalated implementer floor, then a natural failure, same-task second assignment, accepted
integration, and independent test. No new paid call was justified; S8 remains failed/incomplete.
Ordered gates passed: Ruff, strict mypy, unit/contract 928 passed and 2 skipped, smoke, full suite
1,232 passed and 5 skipped. Package/release checks still require renewal on this source revision.

## S5 diagnosis and live acceptance update (2026-09-28, latest)

[The S5 diagnosis](s5-diagnosis-2026-09-28.md) supersedes older S5 withholding statements below.
Fresh run `31f697cc-3018-43c8-a6fe-af638ad819e5` passed the main adaptive-plan path: two accepted
explorers, checkpoint/revision 2, later scoped writer integrated, independent parser tests 4/4,
and mounted `/plan` replay matching persisted IDs/states. Historical explorer causes remain unknown.
Explicit manual GPT-4.1 routes are authorized; missing automatic capability evidence still blocks
S8 escalation and does not prohibit a fresh manual S5 run. The prior 0.65 floor was S8-specific.
New child guidance requires full workspace-relative source references; a red/green regression and
all ordered offline gates passed (927 unit/contract, 1,231 full-suite passes). Package/release checks
from earlier commits are historical and require renewal for this source revision before release.
The call audit now has 877 unique IDs. This continuation added 56 fully priced calls, USD 0.1995512;
campaign local estimate is USD 3.946369484, S5 allocation remaining USD 1.618440346. Provider billing
is unknown. Other unchecked acceptance, speed, conditional lifecycle, and hosted gates remain open.


Planning baseline: `9f9d1c9ed19b8ad63feea77f0bbc04feef847c55`, 2026-09-27.
This is the active implementation and acceptance handoff. The progress section records changes made
after its baseline; the dated sections below still define remaining work.
The companion execution checklist is [todo.md](todo.md).

## Implementation progress (2026-09-28 UTC)

Offline implementation now covers R1, R2, R3, R4a, R4b, R6, R7a, R7b, and R8. Their focused tests
passed. R7a runs two isolated writers through an evidence-only checkpoint acknowledgement, operator
parser/report tests, and a mounted FIFO follow-up. R7b runs two read-only discovery children, commits
the evidence-backed writer revision, integrates its scoped result, and independently passes the
focused parser tests. The R9 offline edge audit also passed: mounted question cards retain focus and
visible Answer/Cancel controls at 80x24 for free-form and fixed-choice questions; related tests cover
pending-question refusal, transient queue disposal, canceled-plan ownership, non-TTY resume/continue
guards, admission failure, and admitted-but-unlaunched terminalization. At this original checkpoint,
active-child live cancellation and settled accounting remained open; the 2026-09-28 R9 live
cancellation pass is recorded below. Conditional permission/question edges remain open.

Final ordered offline gates passed on clean commit `9d28dc4`: Ruff, strict mypy (126 files),
unit/contract (927 passed, 2 skipped), smoke, and full suite (1,231 passed, 5 skipped). The local
Windows package check and release check also passed on that exact commit, using the retained wheel
and sdist under `out/live-agentic/release-candidate-9d28dc4/`; the release evaluation and benchmark
passed. Graphify rebuilt the code graph. Three exact-candidate timing runs measured 161.856/153.587/
151.763s external wall (median 153.587s, range 10.093s): 6.446% under the older 164.17s baseline
and 22.251s above the 131.336s 20% target. R5 currently has no eligible S8 automatic retry in the
retained snapshot; the historical S8 replay is diagnostic evidence, not a fresh route qualification.
The original 9d28dc4 progress checkpoint predates the live continuation recorded below. R14 still
needs exact-candidate hosted Windows/Linux matrix evidence and branch-protection verification; local
checks alone do not make the release eligible while acceptance items remain open.

### Live continuation update (2026-09-28)

S4 now passes its live criteria: two accepted child results, successful checkpoint, observed 15.783365
seconds of child overlap, completed FIFO follow-up, no out-of-scope changes, and 3/3 independent
parser/report/integration tests. S6 passed its same-run durable question/resume/exporter criterion.
A separate child write-scope denial also passed live, distinct from S7's lead traversal denial. The
R9 active-child cancellation path also passed live with settled task/attempt/node/reservation state,
a visible discarded FIFO prompt, no follow-up call, no warning, and no fixture changes; natural
permission/question edges remain open. S5
remains withheld because its historical explorer failures lack sufficient cause evidence. S8 remains
failed/incomplete after a natural result-validation failure and an ineligible retry. S1-S3/S6
presentation comparisons, the 20% timing objective, and R14 hosted/branch protection evidence remain
open.

Ordered offline gates and package-check passed on source commit `6a99a32`: Ruff, strict mypy (126
files), unit/contract (927 passed, 2 skipped), smoke, full suite (1,231 passed, 5 skipped), and
package build/install. Clean-worktree release-check passed on `4f0b342`; the evidence updates in this
documentation-only continuation are separately link-checked. `CALL_COST_AUDIT.csv` contains 821
unique call IDs; `COSTS.csv` cumulative local estimate is USD 3.746818284, with USD
4.753181716 to the USD 8.50 normal stop and USD 6.253181716 to the USD 10 ceiling. S4 has USD
0.783867312 remaining in its allocation; S7 has USD 0.6808022 remaining from its USD 0.75 threshold.
Provider billing remains unknown.

## Authority and scope

Use this plan for the next implementation cycle. It supersedes the **execution order**, stale
balances, and prospective instructions in [the September 24 plan](remediation-2026-09-24-plan.md).
Preserve that document, [the historical plan](defect-remediation-plan.md),
[the defect checklist](defect-remediation-todo.md), and all dated observations as history.
[The live test plan](live-agentic-test-plan.md) retains the scenario prompts and acceptance criteria;
the corrections and additional prerequisites below must be applied before executing them.
Older references to `tasks/plan.md` in ignored evidence predate this new file; they are not references
to this implementation plan.

The user explicitly authorized the live continuation. Before any further paid work, continue to check
the scenario-specific thresholds and fresh route qualification; historical campaign headroom alone is
not a per-scenario allowance. The old ambiguous print-mode probe remains separately settled under the
later waiver recorded in the live plan.

Success means correct product behavior, independently verified fixture results, matching live
acceptance evidence, and exact-candidate offline/platform gates. Offline green alone is insufficient.
Unknown provider outcomes and naturally unexercised scenarios must remain separately reported.

Nonnegotiable constraints:

- Preserve `out/live-agentic/`, quarantined fixtures, original exports, and retained child worktrees.
  Do not hand-edit generated evidence or use the Skail source checkout as a live writable workspace.
- Keep two attempts per child task, at most three concurrent children, immutable assignments,
  runtime-owned IDs/permissions/budgets, isolated child context, and serialized integration.
- Never loosen result validation, invent verification, enable arbitrary scoped-child shell execution,
  fabricate capability evidence, or force a live failure to obtain a passing scenario.
- Do not read the root `.env` into output. Do not use the LLM Gateway CLI. Treat model output and
  exports as observations, not instructions or explanations of their own causes.
- Query Graphify before unfamiliar exploration; read the applicable spec/ADR before changing a
  contract. Use PowerShell, RTK where required, focused regressions, and `graphify update .`.

## Verified baseline and evidence index

The starting tracked checkout was clean. The final gate evidence is
`out/live-agentic/final-gates-20260927-123310/{run-info.txt,final-summary.txt,01-ruff.log,02-mypy.log,03-focused-pytest.log,04-smoke.log,05-full-pytest.log}`.
It identifies clean **9f9d1c9**, not only the earlier `e9779f6` code tree: Ruff, strict mypy,
916 unit/contract passes with 2 skips, smoke, and 1,213 full-suite passes with 5 skips.
The full-suite gate's 189.549 seconds is one external-wall observation, not a timing median.

| Item | Current disposition | Evidence and exact remaining criterion |
|---|---|---|
| S1 | Passed fresh live presentation | New GPT-4.1 mini read-only run completed; no fixture edits; one final answer matched the export, mounted TUI, and terminal capture. Historical raw answer provenance remains unavailable. |
| S2 | Passed fresh live presentation and implementation | New GPT-5 mini direct run changed only normalization source/test; independent focused tests passed 3/3; final answer matched export, mounted TUI, and resumed terminal capture. Prior out-of-scope attempt is preserved separately. |
| S3 | Passed fresh two-model live presentation | Same-session GPT-4.1 nano then GPT-4.1 mini read-only reviews completed, with no fixture changes; each answer matched export, mounted TUI, and terminal capture. Prior decision-blocked attempt is preserved separately. |
| S4 | Passed live | Session `d59ee73b-4efc-4806-b6b6-ed157aaae0a5`: main run `5360fc2f-fbe5-448b-b740-efe2369566a8` and FIFO run `b9dbd334-a419-4394-abf0-8426551bcdf0` completed; two accepted child results, checkpoint, 15.783365 seconds observed overlap, and 3/3 independent focused tests. Evidence: `s4-live-remediation-20260928T101200Z-fifo-direct/`. |
| S5 | Passed main live path | Fresh run `31f697cc-3018-43c8-a6fe-af638ad819e5`; accepted discoveries, checkpoint/revision, integrated scoped writer, independent 4/4 parser tests, mounted plan replay. Historical causes remain unknown. See [diagnosis](s5-diagnosis-2026-09-28.md). |
| S6 | Passed live and presentation | Session `6b480702-4fcf-485e-9685-f9d7acca4dd2`, run `e533a686-5cbd-4f41-a41b-3e9abe322a2c`: durable JSON question restored/answered, exporter/focused test passed. A no-call resume captured the final answer, matching the export and mounted TUI. Earlier operator-edited fixture remains quarantined. |
| S7 | Passed, lead boundary only | Run `6b2da5e7-797c-4502-9d91-19742ac9ff34`: traversal write denied and outside file absent. This remains separate from the child-scope denial. |
| Child write denial | Passed live | Run `ae17ce6a-3a03-4f75-afc6-77f0c1381c8e`, child task `cdf0e48b-b628-48d6-a27d-2336d5856c09`: task-owned `write_file` denial `write is outside the delegated task scope`; parent fixture unchanged and out-of-scope test absent. Evidence: `child-scope-denial-live-20260928T103251Z-scope-mismatch/`. |
| R9 active-child cancellation | Passed live | Session `b1afdf23-3f8e-48a7-bcd1-49bbdfb72c6f`, run `2fdb4d2b-0a4b-4007-ac02-de0fb3f1b4d3`: two child calls active at Ctrl+C; child tasks/attempts, plan nodes, and reservations terminal; queued prompt shown then discarded; no later provider start, warning, or workspace change. Permission/question edges remain open. |
| S8 | Passed live September 29 | `s8-fix-20260929/verification.json`, run `6e929683-31ff-49e9-b69d-7e1c76d269ec`: natural GPT-4.1 nano failure, same-task selected GPT-5 mini retry, accepted integration and independent parser test 1/1. See [resolution](s8-resolution-2026-09-29.md). Earlier failed runs remain historical. |
| Suite speed | Open | Exact candidate `557b3fc`: 238.548/210.763/237.399 seconds; median 237.399, 106.063 seconds above the 131.336s target. Previous `9d28dc4` median 153.587 is historical; no established causal gain. |
| Release qualification | Incomplete | Clean isolated candidate `557b3fc` passed package/release checks with retained artifacts and benchmark/evaluation reports. Hosted Windows/Linux matrix, Python 3.12–3.14 CI evidence, and branch-protection verification remain. See Task R14. |

All evidence paths in this table are relative to `out/live-agentic/` unless stated otherwise.
Also reviewed: `BUGS.md`, `OUTPUT_MISFORMATS.md`, `RUN_LOG.md`, `COSTS.csv`,
`CALL_COST_AUDIT.csv`, the S6 corrected/postfix exports, and the S8 frozen pricing snapshot.

At the original 2026-09-27 baseline the read-only cost audit found 600 unique call IDs. After the
2026-09-28 continuation, the append-only audit has **821 unique IDs, zero duplicates, and no
arithmetic mismatches among priced rows**. Overlapping export snapshots are not summed; `COSTS.csv`
holds the cumulative local stop estimate.

The original 2026-09-27 campaign snapshot was USD `3.019357484`. The append-only ledgers now
reconcile the current in-house campaign stop at USD **3.746818284**, including measured new calls,
conservative settlements for tokenless calls, and the retained historical stop buffer. Current
headroom is USD `4.753181716` to the USD 8.50 normal stop and USD `6.253181716` to the USD 10
ceiling. This arithmetic excludes historical unknowns and is neither provider billing nor new
per-scenario authority. The earlier hourly USD 0.0018 observation and actual provider billing remain
unattributed/unknown; six legacy calls without usage remain outside this campaign total.

## Diagnosis: what the code and evidence actually establish

### D1. S6 plan guidance does not describe the write contract adequately

`agents/lead.py:TASK_PACKET_GUIDANCE` gives only a read-only discovery example.
`runtime/decisions.py:execution_decision_tool` exposes `plan`/`revision` as dictionaries, so the
provider-facing tool schema does not explain nested `PlanNode` fields or `EffectScope` values.
`domain/plans.py` requires scalar `read`, `workspace_write`, `external_write`, or `unknown` effects;
permissions/admission still determine which are authorized. `_actionable_plan_invalid` always
recommends planned mode and a checkpoint-only read skeleton, including for bounded work that could
use direct mode. This is a concrete guidance gap, not proof that Pydantic rejects a valid plan.

The latest S6 export has safe invalid-type paths at sequence 16 (one node) and 20 (two nodes).
The actual rejected arguments are absent; do not infer that the model literally submitted the string
`write`. Its final prose expresses scope confusion, but prose is not the tool argument payload.

### D2. Exhausted rejected decisions can end in clarification prose

The S6 prompt sets `requires_user_answer=True` and no required execution mode. After JSON is
accepted, `resume_interrupted` checks required question/mode and four stale-result shapes, then
can mark the run completed. It does not apply the initial path's `_gated_noop_requires_blocked`.
That helper itself only recognizes `execution.decision_required` and treats **any** completed tool,
including `ask_user`, as work; it does not recognize two rejected plan attempts.

`RuntimeActivityMiddleware` calls `observe_progress()` on each model response with tools, resetting
the consecutive-error streak. The two S6 rejection strings differ by their safe field paths.
A read-only replay of these strings through `FailureMonitor`, with those progress resets, returned
no stop signal for either. Thus the earlier identical-error regression does not cover this sequence.
The run-wide 32-call ceiling still applies. This explains a reachable path, not a claim that every
completed conversational clarification violates the existing lifecycle contract. R2 defines and
tests the narrow exhausted-decision behavior before changing it; preserve ordinary final answers.

### D3. The mounted Ctrl+C regression exits its context before sending Ctrl+C

In `tests/integration/test_tui_question_quit_resume.py`, the first `async with app.run_test()` ends
before `await pilot.press("ctrl+c")`. The context's shutdown precedes the keypress. The test proves
some durable restore behavior, but cannot establish that Ctrl+C caused that shutdown. It also types
the prompt character by character and polls two durability conditions. The saved timing series names
it as the 22.36-second duration leader; the overall slowdown's cause has not been established.

### D4. Child JSON guidance and actual verification capability

The live child result guidance now contains complete `ArtifactRef` and `VerificationResult` shapes,
allowed statuses, and explicitly says that a file digest does not prove a test ran. The checkpoint
payload now includes a copy-ready, validated evidence-only `ExecutionDecision` with a full next
revision and `PlanRevision` metadata. A red/green integration regression validates that example;
source commit `6a99a32` passes the ordered offline gates. The final S4 run accepted both child results
and completed the checkpoint. `agents/result_evaluator.py` continues to reject malformed JSON,
wrong identities, invalid fields, missing criteria, bad file references, and unsupported references.

There is a separate capability limit: scoped or isolated child execution sets
`execute_allowed=False` at `run_controller.py:3736`, and `tools/assembly.py:execute` rejects it.
The live S4 prompt nevertheless requires each child to run pytest and compute a SHA-256 with Python.
The child guidance does not explain this limitation. `_validate_evidence_at` validates a file digest;
it does **not** prove a pytest invocation or its assertions. Do not count a source-file hash as a
successful test receipt. R4 must resolve this before another writer scenario, without opening a
shell escape around resource scopes.

### D5. Dirty worktree reuse blocked a same-task retry

The R6 controller regression reproduced the source path: attempt one retained a dirty managed
worktree, and attempt two called `materialize` with the same task ID. Previously, the target path
caused `workspace.worktree_exists` before the second model could resume the task. R6 now stores a
bounded ownership record outside the child-writable worktree, validates task/snapshot/branch/base
identity, and reopens the same partial worktree. It consumes the record before execution and fails
closed on mismatch. A fresh offline controller regression confirms two attempts, retained partial
bytes, successful changeset integration, and cleanup. This was not the cause of S8, whose retry was
blocked earlier by route eligibility.

### D6. S8 preflight qualified attempt one, not automatic escalation

`pricing-snapshot-S8-2026-09-26-tui.json` records `auto_eligible=false` for GPT-4.1, GPT-4.1-mini,
and Qwen3.8 Flash. The child assignment's 142 `routing_inputs` enable exactly those three.
`task_graph.py` excludes the failed Qwen model; `run_controller.py` drops the ordinary first-attempt
profile pin for escalation; `requirements.py` raises the routine implementer floor to 0.65.
`selector.py` checks enabled state before automatic eligibility and reports the most frequent
exclusion as its aggregate binding reason. The recorded offline replay in `RUN_LOG.md` found
`model_excluded=1`, `auto_ineligible=2`, `model_disabled=139`.

Therefore `model_disabled` does not identify one wrong model to enable. The surviving enabled
models lack automatic eligibility. The export omits some full capability inputs, so it cannot prove
that any other candidate meets the stronger floor. Fix preflight qualification, not the eligibility
guard. A rejected second attempt has an attempt row, but no successful second assignment/provider
execution; preserve that distinction in new documentation.

### D7. Replayed terminal events omit final answer text in the TUI

`tui/projection.py:apply_snapshot` clears transcript items and replays events. `apply_event` has no
`run.completed` output-rendering branch. The live-only `_apply_run_result` in `tui/app.py` appends the
answer separately. A read-only replay of the latest S6's 23 exported `EventEnvelope`s produced ten
transcript rows, zero lead rows, and no saved final answer. This establishes a replay defect, not
the cause of every historically blank overlay. R8 must also test the live overlay path separately
and avoid duplicate answers when both the event and the returned result are available.

### D8. Historical S5 causation and historical provider billing are unrecoverable locally

The S5 export cannot distinguish provider failure, invalid result, or an older runtime failure.
New category/path diagnostics and failure handoffs make future runs inspectable; they do not fill
in old records. The historical plan permits a distinct qualified corrective route as an alternative
to reconstructing the impossible historical cause. Document that decision explicitly; otherwise S5
stays withheld. Paid calls with uncertain outcomes must never be replayed to investigate them.

## Ordered implementation tasks

Every code task starts with a failing deterministic regression, implements the smallest change,
passes focused checks, and updates the affected public contract in the same change. Existing tests
are starting points, not proof that the proposed regression already exists. Split a task further if
its implementation exceeds roughly five source/test files. Commands below are run at repository
root; substitute the same verified Python interpreter consistently. No provider-live flag is used.

### R0 — Establish one current evidence and qualification manifest

Dependencies: none. Scope: documentation/evidence accounting.

Record source SHA, fixture SHA, isolated HOME/state paths, schema-v2 hashes, scenario/run/task/attempt
IDs, live acceptance status, and measured versus estimated cost. Reconcile all latest complete
exports bidirectionally against call IDs, accounting for overlapping snapshots and ledger scopes.
Record which historical live authorizations remain usable and each proposed scenario's allowance.
Correct prospective references in the live plan/checklist without overwriting historical entries.
Do not re-register the already-audited `be73b1cc` S4 calls.

Acceptance: every unresolved checklist item has an owner task below; no missing/duplicate new call;
one current total with historical unknowns separated. Verification: Decimal recalculation and
call-ID set comparison; local link check. Files: three current plan/checklist documents plus appended
ignored campaign records when execution actually creates evidence.

### R1 — Correct the durable TUI quit/resume regression

**Status: implemented and focused test passed.** The regression now sends Ctrl+C while the app is
mounted, verifies the quitting state, and restores the same question using fresh store instances.
Character-by-character prompt entry was removed from this state-transition test; Enter and Ctrl+C
remain actual Textual events.

Dependencies: R0. Scope: small test correction.

Edit `tests/integration/test_tui_question_quit_resume.py`: send Ctrl+C while the first app is mounted,
after the question and owning checkpoint are durable. Assert the shutdown handler/worker completes
before leaving the test context. Reopen fresh store/controller/app instances from the same paths,
not merely a second app sharing all open store objects. Assert exactly one restored question, same
run/task/assignment, no pre-answer file, one accepted JSON answer, no duplicate model invocation,
only exporter/test writes, one final completion, and independent focused pytest success. Keep
explicit state barriers; do not use a sleep as the correctness condition. Remove the redundant
asyncio marker when editing this test, consistent with repository conventions.

Verification: focused test with `-W error::RuntimeWarning`, plus
`rtk pytest tests/contract/test_question_resume_contract.py tests/unit/test_tui_interactions.py -q`.
No live pass may be claimed from this correction. Keep the real mounted keyboard/shutdown boundary.

### R2 — Make exhausted decision termination consistent across initial and resumed runs

**Status: implemented and focused regressions passed.** Both initial and resumed no-work paths now
block with execution.decision_exhausted after two decision validation rejections and no admitted
decision. One failed decision retains its repair. Ordinary final answers, accepted decisions, and
successful operational work do not match the guard.

Dependencies: R1. Scope: runtime lifecycle plus focused regression and ADR amendment.

Use `tests/integration/test_phase10c_resume_dispatch.py` to reproduce the exact S6 event shape:
question, durable restart, accepted JSON, two different invalid-type plan rejections, final
clarification prose, zero operational work. Also test the same rejection sequence without a
question, and a legitimate no-tool final answer. Do not pretend synthetic malformed arguments are
the missing historical arguments.

Define the narrow invariant: once initial decision repair is exhausted with no admitted decision,
an attempted operational run terminates blocked/failed with the existing decision-exhausted
diagnostic rather than reporting successful execution. Share this completion check between initial
and resume paths; exclude `ask_user` and decision bookkeeping from operational progress. Preserve a
single valid repair, later legitimate questions, ordinary answer-only completion, truthful budget
settlement, and the 32-call ceiling. Do not extend waiting-prefix regexes to detect arbitrary prose.
Keep generic repeated-call semantics unchanged unless a separate regression justifies a change.

Likely files: `runtime/run_controller.py`, `runtime/decisions.py`, the resume integration test,
`tests/contract/test_execution_decisions.py`, ADR 0009 (and its feature/spec references).
Acceptance: one truthful final lifecycle outcome, no unexpected extra call/dispatch/write, and no
false block of ordinary final answers. Verification: the two named test modules and
`tests/unit/test_live_r5_residual_faults.py`; inspect committed task/attempt/budget state.

### R3 — Supply validated plan examples and mode-appropriate repair guidance

**Status: implemented and contract tests passed.** The lead guide includes a scoped writer example;
rejection guidance retains direct, discovery, or planned mode and lists valid effect scopes. Explicit
write permissions remain enforced by runtime policy. A staged read-only discovery followed by an
explicit scoped implementation is recognized without treating the discovery scope as a global
no-write instruction.

Dependencies: R2. Scope: lead/tool guidance, not relaxed validation.

In `agents/lead.py` and `runtime/decisions.py`, describe scalar effect values, a scoped
`workspace_write` implementer, and the required checkpoint/revision flow. Show direct execution for
bounded local work after a user choice. Repair messages must retain the submitted mode when valid
or explain its required shape, rather than universally directing the model into planned mode.
Keep existing dictionary/normalization compatibility unless a contract-tested typed tool schema is
strictly necessary. Derive/check examples against `domain/plans.py` and `domain/decisions.py` so
guidance cannot drift. Do not echo submitted values or raw validator messages.

Acceptance: valid direct/read/scoped-write examples are admitted; object/list/numeric effects and
invalid enum strings are safely rejected; exactly-two/profile/scope constraints and bounded repair
remain enforced. Verification: `tests/contract/test_execution_decisions.py`,
`tests/contract/test_p5_decision_task_normalization.py`, `tests/unit/test_lead_intent.py`, and a
same-run JSON continuation using the actual bound tool surface. A guidance check alone is not S6.

### R4a — Make child result guidance complete and demonstrably deliverable

**Status: implemented and focused tests passed.** The assembled child receives allowed statuses,
artifact/verification object shapes, source-reference rules, and an explicit distinction between
runtime file digests and command execution.

Dependencies: R3. Scope: child result prompt and parser-facing contract tests.

Use one bounded model-facing result contract at the child assembly seam rather than two partially
overlapping prose suffixes. Include allowed statuses, optional/owned task identity, artifact objects
`{kind, path, digest}`, exact criterion matching, evidence text, and `evidence_ref` shape. Give
separate read-only analysis and writer examples. A read-only analysis needs real path:line evidence
and retains `model-authored` authority; a writer needs a valid runtime-checked reference. Failed or
blocked results must report unavailable verification honestly. Never require child access to the
lead transcript or copy raw rejected output into handoff/events.

Likely files: `runtime/run_controller.py`, `agents/result_evaluator.py` only if a reproduced parser
bug exists, `tests/contract/test_task_result.py`, and a focused child assembly integration test.
Acceptance: examples validate using real files/digests/source references; wrong status/artifact
type, forged ID, false/skipped/missing criterion, and invalid reference still fail. Verification:
`rtk pytest tests/contract/test_task_result.py tests/integration/test_lead.py -q`, including an actual
assembled child's serialized final message. Do not add provider schema binding merely because
`response_schema` exists; any such change requires adapter contract coverage.

### R4b — Resolve scoped-writer verification before declaring writer scenarios eligible

**Status: resolved through the operator-verification contract.** `file_digest` is a runtime-owned,
read-only tool that returns a stable SHA-256 for a readable, non-sensitive workspace file, bounded
to 256 MiB and the same canonical workspace boundary. Scoped children do not gain arbitrary shell.
The result prompt explicitly says a file digest proves bytes only, not a test or build.

The accepted workflow assigns each scoped writer only the bounded implementation criterion and
runtime-checked artifact references. After accepted changes integrate, the trusted operator runs the
focused child tests and integration test. The live S4 prompt names the operator as the test actor.
This retains the test acceptance checks without representing a child-authored string or file hash as
a successful test receipt. A project test runs as native code under the trusted operator's existing
command policy; the implementation does not claim that path-scoped child shell access is safe.

Files: `tools/{assembly,backend}.py`, `agents/lead.py`,
`runtime/run_controller.py`, `tests/integration/test_task_graph.py`,
`tests/integration/test_filesystem_boundary.py`, `tests/integration/test_lead.py`,
`docs/skail/{FEATURES,ARCHITECTURE}.md`, and the live S4 procedure. Verification passed through an
assembled child with a nonempty write scope, traversal/sensitive-path/oversize denial tests, result
contract tests, operator focused tests in the S4/S5 integration pilots, Ruff, mypy, and the full suite.
The digest does not attest operator test results; every live pass still requires captured independent
command output. This change is not evidence about the historical malformed artifact fields.

### R5 — Qualify a real retry route and preserve diagnostic evidence

**Current status: passed for the September 29 selected roster.** Reviewed profiles, authenticated
pricing, real retry assignments, preserved failure handoff, integration, and independent testing
are recorded in [S8 resolution](s8-resolution-2026-09-29.md). The older observations below explain
why the prior roster was ineligible; they do not describe the new qualified run.

Dependencies: R0; writer eligibility also needs R4b. Scope: preflight and routing evidence.

Build a provider-free preflight using the actual config/catalog/health/candidate snapshot, profile
overrides, UI enabled-model set, task requirements, and budget estimator. Evaluate both the intended
first route and the escalated route after excluding the first model. Record per-candidate exclusions,
not only the modal binding reason. For S8 require a real alternative with trusted automatic
eligibility and fit at least the computed floor (0.65 for the observed routine implementer).
Prices/tool support/manual selectability do not supply capability evidence. Missing evidence is a
configuration/qualification block, not grounds to fabricate scores or toggle `auto_eligible`.

Starting points: `routing/{selector,requirements,assignment}.py`,
`runtime/run_controller.py:assign_child/child_candidates`, `cli/main.py:_build_runtime_models`,
`tui/app.py:set_enabled_models`, `tests/integration/test_assignment.py`.
Use the persisted S8 inputs to show the observed exclusions; label synthetic absent profile fields.
If rejection diagnostics cannot retain the retry snapshot, add a small allowlisted diagnostic
record containing the actual failed attempt's requirements/revisions/exclusion counts. Never
export credentials, arbitrary config contents, or the raw provider reply.

Acceptance: qualified retry yields a distinct immutable assignment; ineligible retry makes zero
provider calls with actionable exclusions; the first attempt's recorded failure is not overwritten
by the parent plan's later block; live eligibility is not inferred from synthetic tests.
Verification: existing selector/assignment tests plus controller-level first-pin-to-auto-retry
coverage. Freeze current qualification evidence again immediately before any authorized live run.

Latest route-only qualification (2026-09-28): the fresh 142-model catalog has zero automatic
candidates with trusted capability evidence, tools/structured-output support, and the observed
0.65 routine implementer retry floor. The isolated provider config currently enables only
`gpt-4.1-mini`, whose price/support facts are current but whose capability vector is absent. S5 stays
withheld and S8 stays failed/incomplete; do not toggle eligibility or infer capability. Snapshot
summary: `out/live-agentic/child-scope-denial-live-20260928T103251Z-scope-mismatch/model-route-qualification.json`.

### R6 — Preserve failed work safely across a same-task worktree retry

**Status: implemented and real-controller regression passed.** Retention metadata moved outside the
child workspace. Attempt two authenticates snapshot, task, branch, base commit, and bounded metadata,
then reopens the same worktree and consumes the record. The controller regression preserves a partial
file from a failed first attempt, verifies attempt-two assignment, validates the final digest, and
integrates once.

Dependencies: R4a and R5 offline coverage. Scope: worktree lifecycle.

Add a real temporary-Git controller regression: first child writes within scope and returns a
genuine scripted verification failure, a distinct eligible second model receives attempt two under
the same task, observes the first attempt's bytes, repairs, returns valid evidence, and integrates
once. This is an offline synthetic failure, never a live S8 trigger. Avoid monkeypatching away
`WorkspaceManager`, filesystem tools, capture, or integration.

If the predicted `workspace.worktree_exists` block reproduces, retain an authenticated task-owned
workspace across attempts or explicitly reopen it after validating snapshot/task/path/branch
ownership. Do not delete/recreate dirty state, reset partial work, or silently adopt an arbitrary
existing directory. Keep runtime retention metadata out of model changesets. Cleanup only after
successful integration; final failures retain evidence. Reject mismatched owner, stale snapshot,
untrusted symlink, and third attempt.

Likely files: `runtime/run_controller.py`, `runtime/workspaces.py`,
`tests/integration/test_task_escalation.py`, `tests/unit/test_workspaces.py`; add capture tests only
if metadata treatment changes. Acceptance: same task, two distinct attempts/assignments, preserved
partial bytes, accepted result, one integration, no orphaned lease/reservation or overwritten user
change. Verification: those files plus `tests/integration/test_delegation_controls.py`.

### R7a — Prove the complete S4 coordinator path offline

**Status: implemented and integration test passed.** Two event-synchronized scoped writers overlap,
return validated results, integrate separately, revise their running checkpoint with prerequisite
evidence and no placeholder task, pass independent focused parser/report checks, and dispatch one
queued read-only TUI follow-up.

Dependencies: R3, R4a/R4b; R6 if retries are included. Scope: one realistic integration test.

Compose existing isolated-writer, plan-dispatch, checkpoint, and queue coverage into the missing
vertical path. Use the real assembled filesystem tools, exactly two disjoint implementers, real
result validation and serialized changeset integration. Synchronize children with events, not
timing sleeps, and require observed overlap. The checkpoint is not passive: current
`_dispatch_admitted_plan_agents` requires a valid next revision to settle it. Supply and test a
revision that adds no extra agent when all S4 work is complete, using only provided evidence refs.
Document this in the live S4 prompt; simply asking the lead for a final answer would leave the
checkpoint blocked even after both children succeed.

Acceptance: two results accepted, parent files integrated, checkpoint succeeded, no duplicate
`task()` dispatch, one queued read-only follow-up after completion, and independent integration
test pass. Verification: `tests/integration/test_delegation_controls.py`,
`tests/unit/test_tui_interactions.py`; new end-to-end composition may use a dedicated integration
module. Failed/blocked parents must clear the queue, not execute it to satisfy FIFO.

### R7b — Prove the S5 explorer/checkpoint/revision path offline and make a retry decision

**Status: implemented and integration test passed.** Two source-backed read-only results settle the
checkpoint; revision two adds exactly one scoped implementer; runtime digests validate the changed
file; independent focused parser tests pass after integration. The same staged prompt now keeps the
initial discovery read-only without denying its later scoped writer.

Dependencies: R4a, R5, R7a; R4b for the added writer. Scope: adaptive-plan integration.

Run two actual read-only explorer profiles with distinct scopes and inspected path:line findings;
validate each serialized result and preserve analysis authority. Verify revision 1 cannot release a
writer. At the checkpoint, submit the complete revision-2 plan plus `PlanRevision`, keeping original
IDs/dependencies and adding exactly one implementer. The revision commit settles the running
checkpoint; the live plan must not require a completed checkpoint **before** that revision can be
submitted. Assert no writer starts before the accepted revision/checkpoint transition. Test missing,
invented, and stale revision evidence as negative cases.

Starting points: `tests/integration/test_delegation_controls.py` (existing discovery test uses one
discovery child, not the complete S5 shape), `tests/integration/test_plan_persistence.py`,
`runtime/run_controller.py:_checkpoint_evidence_refs`, `agents/result_evaluator.py`.
Acceptance: accepted discoveries, one evidence-backed revision, scoped implementation, and
independent parser check preserving permissive behavior. Verification: these integration modules
and task-result contracts.

Produce a written S5 eligibility decision: either a specific corrected assembled path and distinct
qualified route justify one bounded fresh run, or S5 remains withheld with the missing prerequisite
named. Do not condition all future work on recovering unavailable historical raw text, and do not
claim the historical cause is now known.

### R8 — Restore final answers from durable events exactly once

**Status: implemented and projection, interaction, and mounted-display tests passed.** run.completed
now projects the shared presenter output to a stable run-keyed answer item. Applying the returned
result after the live event does not duplicate it; snapshot replay renders structured answers once at
80x24 and 120x40.

Dependencies: R0; independent of child fixes. Scope: projection/presenter and mounted UI tests.

Add a pure projection regression using a redacted `run.completed` payload and then snapshot replay.
Render its answer through the shared presenter with a stable event/run identity. Coordinate
`SkailApp._apply_run_result` so live event delivery plus returned output does not duplicate the
answer. Retain a fallback for controllers without a persisted output event. Keep structured
verification in the export and ordinary requested technical prose in the answer; no arbitrary line
stripping. Test repeated snapshot apply, duplicate events, structured/plain/missing output, multiple
runs, redaction, and replay of older exports without final text.

Files: `tui/projection.py`, `tui/app.py`, `runtime/presentation.py` if needed,
`tests/unit/test_tui_projection.py`, and the existing TUI output/presentation test module located via
Graphify. Also inspect `tui/overlays/transcript.py` in a mounted test before assigning the historical
blank-overlay cause to this replay defect.
Acceptance: current and restored final answer appears once, matches the presenter applied to export
output, and preserves ownership. Verification: projection/presentation tests and one real Textual
overlay pilot at 80x24 and a normal laptop terminal size.

### R9 — Exercise remaining ownership, shutdown, question, and CLI edge cases

Dependencies: R1/R2/R8; active-child variants need R7a. Scope: separate small evidence slices.

Reuse existing regressions; add only missing independent boundaries. Record each live observation
separately from the successful S4 run:

1. Queue a follow-up, cancel while child work is actually active, and verify settled
   task/attempt/node/lease/reservation state before exit, no traceback/unawaited coroutine, and no
   follow-up call. Cover Ctrl+C and composer `/quit`; typing `/quit` into a question input is an
   answer attempt, not a command test. Host-exit behavior can remain a named offline boundary if a
   real host-exit capture is unavailable; report it rather than implying live coverage.
2. Cancel a plan, start an unrelated run in the same session, and verify fresh run/thread ownership.
   Attempt a new prompt while a question is pending and check visible refusal; restart to establish
   that transient queued prompts are not restored. Do not infer historical queue persistence.
3. Show a genuine free-form question and fixed-choice question with compatible copy, distinct
   Answer/Cancel controls, and 80x24 focus/visibility. Observe an actual permission Approve/Reject
   interaction only when a legitimate scoped operation requires it; otherwise retain unexercised.
4. Verify no-prompt non-TTY `--resume` and `--continue` return before session/provider activation in
   an isolated, provider-disabled process. This CLI guard check is not a substitute for live TUI S6.
5. Exercise terminalization of admitted-but-unlaunched nodes and pre-assignment exceptions via
   deterministic tests; match live evidence if it arises. Do not induce paid transport failures.

Files/read seams: `tui/app.py`, `tui/widgets/interrupts.py`, `runtime/interrupts.py`,
`sessions/{checkpoints,recovery,journal}.py`, `cli/main.py`. Tests:
`test_tui_interactions.py`, `test_phase10c_resume_dispatch.py`, `test_cli_boot_split.py`, and
`test_tui_commands.py`. Acceptance: one owner per transition, no unwanted run/provider call,
durable questions preserved, accurate terminal state. Do not mark a pending live item closed solely
because these already-green regressions remain green.

### R10 — Run eligible live acceptance scenarios with independent fixture verification

Dependencies: relevant repairs, R0/R5 qualification, and ordered offline gates. Scope: evidence only
unless a new defect is reproduced and sent back to its owning implementation task.

Preflight every launch: new disposable clean fixture (baseline `113ed8c9...` only after checking its
actual files/test failures), distinct isolated HOME/state, correct source import origin, real
stdin/stdout TTYs in the launched Skail process, completed project trust, visible composer/question
focus, correct model selection, current frozen prices/capabilities, and budget for lead reservations,
children, checkpoint synthesis, and any eligible retry. Use state-driven PTY milestones, not a
hardcoded prompt marker or elapsed-time assumption. Keep an immutable before manifest and capture
the after manifest before operator verification. Do not modify solution or test files manually.

- **S6 first:** wait for the durable question, quit without answering, resume the same session,
  capture the same question/run/task/assignment once, answer JSON, and require Skail to create the
  exporter and focused test in that run. Independently test JSON output, absence of CSV behavior,
  exact changed paths, no pre-answer writes, and no duplicated paid call. Truthful blocking is a
  failure of S6 acceptance, not a pass. Use the corrected R1 event order.
- **S4:** require the R7a sequence in the live TUI, including actual child overlap, both accepted
  results and integrations, accepted checkpoint revision, and one queued follow-up after success.
  Run focused child/parent checks under the R4b verification contract and independently run the
  parent integration test. Child-worktree green alone never passes S4.
- **Child-scope denial, separate from S7 and S4 success:** delegate one bounded child with a scope
  excluding a harmless named file inside the disposable fixture, request that single denied write,
  and forbid fallback paths. Capture task-owned `write_file`/`edit_file` denial and verify the file
  absent in child and parent. A successful unauthorized write fails immediately. This security probe
  must never be repurposed as S8's natural failure.
- **S5 only if eligible:** require both accepted explorer results, checkpoint/revision, writer only
  afterward, correct strict parser behavior and preserved permissive behavior, plus `/plan` versus
  persisted plan/revision/task agreement. Historical S5 remains failed/unknown even after a new pass.
- **S8 only on a natural first-attempt failure:** record baseline/real attempt evidence before
  retry; same task, excluded failed model, eligible stronger new assignment, bounded safe handoff,
  preserved partial work, at most two attempts, accepted integrated result, and independent focused
  tests. If attempt one succeeds, record escalation **unexercised** and stop; never degrade a model,
  disable candidates, alter tests, or introduce a defect to force the path.
- **S1/S2/S3 presentation:** first recover any existing usable capture without new paid work.
  Otherwise perform only an authorized bounded repeat on a fresh appropriate fixture. Capture the
  actual final TUI/overlay and raw structured export; compare using the shared presenter. S3 requires
  both requested models and unchanged files. Do not overwrite the earlier implementation passes.
- Keep **S7 passed** unless its boundary changed. Fold R9 evidence into appropriate authorized
  scenarios where the actual transition occurs; otherwise leave the individual item open.

After each scenario: export schema v2, capture plan/revision/result/changeset records through
allowlisted read-only journal inspection when the export omits them, identify all new call IDs,
recalculate costs with frozen rates, compare model totals, and append evidence exactly once. Record
fixture tests' seeded unrelated failures explicitly; never require a clean baseline's intentional
stubs to pass or hide new failures among them. Stop on the live plan's unsafe-write/secret/replay/
ownership/accounting conditions and on the scenario's allocated call/cost boundary.

### R11 — Profile and optimize the corrected offline suite without deleting coverage

**Status: profiling completed; the suite speed target was retired on 2026-10-03.** The historical
serial median and full top-40 data are documented in PERFORMANCE.md and
out/live-agentic/release-renewal-20260930/timing/. External-wall median is 237.399 seconds,
and the prior `9d28dc4` median is 153.587 seconds. Different test collections and host-load
conditions prevent causal attribution. These measurements no longer carry a pass/fail threshold.

Dependencies: R1; final measurements after behavior/test changes. Scope: measurement, then one small
candidate per commit. Read `docs/skail/PERFORMANCE.md`, `tests/conftest.py`, packaging/CLI/eval
boundaries, and all three saved top-40 reports before choosing candidates.

Measure three serial runs with the same interpreter, plugins, exact command, machine/power state,
cache protocol, environment, test collection, and external stopwatch. Save source SHA/diff identity,
raw output, exit status, durations, warnings, and collected node IDs. Use
`py -3.14 -m pytest -q --durations=40` for comparability with the latest controlled series; RTK can
summarize results afterward without replacing raw timing evidence. Do not compare pytest time with
process wall time or omit package build cost by prebuilding it outside the measured boundary.

First profile R1's mounted test phases: per-character input, durability waits, shutdown, fresh mount,
and independent pytest. Reduce artificial input/setup overhead only while retaining actual Enter,
Ctrl+C, durable restart, answer, filesystem and subprocess boundaries. Next inspect measured duplicate
mount/setup or import costs; preserve at least one real wheel build/install, isolated no-credential
CLI subprocess, security boundary, evaluation execution, and mounted focus/queue/interrupt path.
Do not enable parallel pytest solely to change the diagnostic measurement.

Acceptance: identical mechanism coverage, no unexplained dropped/deselected tests, and retained
raw timing evidence for any future optimization. No suite runtime threshold is required.
Files: only demonstrated bottleneck tests/helpers/scripts plus PERFORMANCE and evidence records.

### R12 — Reconcile every defect/output entry and documentation claim

Dependencies: completed implementation/live slices; can update incrementally.

Use this closure crosswalk; every ID is retained. “Confirmed” below preserves historical evidence,
not a new current-release pass. Reopen if affected behavior changes.

| IDs | Owner / required disposition |
|---|---|
| LIVE-001/002/010/011/012; OUT-007/008 | Historical catalog/direct/compact-UI/UTF-8 guards confirmed; retain. Refresh route qualification in R5; presentation in R8/R10. |
| LIVE-003/004/017; OUT-001/003 | R9 actual provider/active-child cancellation and queued shutdown; existing offline fixes retained. |
| LIVE-005 | 32-call limit confirmed; preserve. R2 covers distinct decision errors; historical identical-call cause stays unknown. |
| LIVE-006/014/035 | R9 ownership, unlaunched-node and pre-assignment terminalization; no retrospective journal repair. |
| LIVE-007; OUT-004 | Expected question confirmed in S6; R9/R10 records remaining S4-context observation. |
| LIVE-008/029/031/032; OUT-011 | Question restore/focus/owner historically confirmed; R1 and live S6 guard against regression; continuation remains separate. |
| LIVE-009/015/023 | Preserve closed test-plan mismatch/expected projection classifications; R4b reconciles the newly identified child verification mismatch. |
| LIVE-013/016/019/026; OUT-009 | Admission/dispatch guidance repaired; R3/R7/R10 prove actual two-writer/checkpoint outcome; R10 child denial closes the scope subcriterion. |
| LIVE-018 | R9 isolated non-TTY guard; no paid fallback invocation. |
| LIVE-020 | Preserve fixed pinned-route diagnostic; R5/R10 verify applicable route/budget evidence. |
| LIVE-021/022/025 | Conservatively settled locally, provider outcomes unknown; do not replay or manufacture a software fix. |
| LIVE-024 | R7b eligibility decision and S5 live acceptance; historical cause remains unknown. |
| LIVE-027; OUT-010 | R2/R3 rejected/no-decision completion, plus matching R10 evidence; no broad ban on conversational final answers. |
| LIVE-028 | Top-level planned phrase confirmed; R9/R7b retain depth/nested-delegation rejection coverage and explicitly label live absence. |
| LIVE-030/038; OUT-012/014 | R1/R2/R3 and same-run live S6 implementation/test; prefix guards alone do not close. |
| LIVE-033/034 | S2 correction/S3 route and fresh S1–S3 final TUI/export comparisons verified September 30; failed preliminary runs retained. |
| LIVE-036; OUT-013 | R4a/R4b/R6/R7 and live S4/S8; no evidence of valid-result rejection in historical exports. |
| LIVE-037 | Offline scope repair retained; separate R10 direct child denial still required. |
| OUT-002 | R8/R10 fresh paired answer presentation passed for S1/S2/both S3 routes and no-call S6 replay; preserve the historical S1 pass and unknown original origin. |
| OUT-005/006 | R9 distinct legitimate permission card and compatible free-form/fixed-choice requests; report unexercised when absent. |
| LIVE-039/040/041/042/043; OUT-015 | New offline-only decision-exhaustion, retained-worktree retry, checkpoint acknowledgement, staged read-only intent, file-digest, and completion-replay defects/gaps are appended to BUGS/OUTPUT_MISFORMATS with focused evidence. All are fixed/clarified offline; no historical live cause is assigned. |

Checklist mapping: old unchecked 5 -> R8/R10; 6 -> R1/R2/R9/R10; 9 and 17 -> R0/R5/R10;
11 -> R7b; 19 -> R11; 20b -> R4/R7a/R10; evidence-update checkbox -> R0/R12.
Old checked speed/profile milestones do not close the unchecked objective. Preserve other checked
offline milestones without claiming they satisfy live acceptance.

Update `SPEC`, `FEATURES`, `ARCHITECTURE`, `CLI`, relevant ADRs, `PERFORMANCE`, and test procedures
only where behavior/claims change. Audit README links/commands read-only unless a real inaccuracy is
found. Reconcile the S4 checkpoint revision and verification-actor wording before using its prompt.
Acceptance: every ID has a status, supporting artifact/IDs, and remaining action or explicit external
unknown; no contradictory current execution instructions. Verification: link/path checks, focused
contract tests, and a diff audit excluding unrelated formatting.

### R13 — Pass the final ordered offline gates

Dependencies: code/tests/contracts finalized, R11 measurement complete, R12 updated.

Run on one candidate revision in this order; capture exit codes and exact source identity:

```powershell
python -m ruff check src tests scripts evals
python -m mypy src/skail
rtk pytest tests/unit tests/contract -m "not provider_live" -q
python scripts/smoke.py
rtk pytest -q
```

If RTK cannot use the intended interpreter, immediately use that interpreter's raw `-m pytest`.
If any check changes the code/test fix, rerun affected focused checks and then the ordered gates on
the final revision. Run Graphify update and inspect the final diff/status. Do not reuse old test
counts as a target or omit new regressions to preserve speed. Acceptance: all gates pass, collection
differences explained, no source-root runtime-state changes, and no new actionable defect ignored.

### R14 — Produce an honest release-candidate evidence package

Dependencies: R10 applicable criteria resolved, R12/R13; performance shortfall explicitly reported.

Read ADRs 0006/0010, `.github/workflows/{ci,release}.yml`, and
`scripts/{package_check,release_check}.py`. Build/inspect/install the candidate wheel and sdist,
then run release verification on a clean candidate. Reuse the exact artifacts by absolute path;
record SHA-256, source commit, environment, raw benchmark/evaluation evidence, and command results.
The commands are `python scripts/package_check.py` followed by `python scripts/release_check.py`;
their `--artifact-dir` options permit retaining/reusing the actual built artifacts. Release-check
lint additionally includes `benchmarks`; do not assume the regular gate covers that path.

Obtain exact-candidate Windows/Linux evidence and the supported Python 3.12–3.14 fast matrix via
authorized CI or equivalent environments. Historical local green is not Linux evidence. Verify
the hosting `CI / Required fast gate` migration separately; repository YAML cannot prove branch
protection settings. If remote execution/settings authority or platform access is unavailable,
report that dependency as blocked, after preparing the reviewable candidate locally.

Final report must separate: passed live, fixed offline/live pending, failed, unexercised natural or
conditional scenarios, withheld/blocked qualification, performance result, and external provider
unknowns. Do not describe a candidate with failed S4/S5/S6 or actionable defects as release-ready.
S8 passed on a natural September 29 failure and stronger same-task retry; preserve that evidence.
Do not push/tag/publish as part of this plan unless separately authorized.

## Dependency checkpoints and stop rules

```text
R0 -> R1 -> R2 -> R3 -> R4a -> R4b -> writer eligibility
R0 -> R5 ---------------------> R6 -> retry eligibility
R3/R4/R6 -> R7a -> R7b --------> S4/S5 eligibility
R0 -> R8; R1/R2/R7a/R8 -> R9
eligible slices + ordered offline checks -> R10
R1 + final regression set -> R11
R10/R11 -> R12 -> R13 -> R14
```

Checkpoint A (R1–R3): real Ctrl+C coverage and truthful bounded decision behavior, selected-format
continuation green offline. Checkpoint B (R4–R7): a scoped child can actually supply valid evidence,
eligible retries preserve work, and the full planned/adaptive coordinator paths work. Checkpoint C
(R8–R10): presentation and live evidence agree with actual workspace outcomes. Checkpoint D
(R11–R14): measured performance, final gates, and exact-candidate release evidence.

Stop a paid scenario when its qualification, natural-failure, permission, accounting, call, or cost
precondition is not met. Continue independent offline tasks. Do not repeatedly retry an unchanged
model/guidance/configuration, or expand a budget because the acceptance evidence is still missing.
If historical evidence cannot answer a question, record that limit and test the current mechanism;
do not fabricate a historical explanation. If a new regression disproves a hypothesis, remove the
proposed source change and retain only the useful test/evidence correction.

## Investigation and implementation verification

Read-only investigation covered the current and historical remediation/live plans and checklist,
all defect/output IDs, relevant run/cost records and final exports, final gate/timing artifacts, and
the source paths for lead intent, decision admission, result parsing/evaluation, child assembly,
retry selection, worktree retention, filesystem scope enforcement, checkpoint revisions, questions,
TUI shutdown/presentation, packaging, and release gates. Relevant spec/features/architecture and
ADRs 0006/0008/0009/0010 were read alongside the code. Graphify was used to locate unfamiliar seams.

Initial planning used read-only probes for intent/gate behavior, event projection, and Decimal/call-ID
reconciliation. The implementation then used only disposable pytest workspaces. It made no provider
generation call and no new live acceptance run. Final source/test verification on clean commit
`9d28dc4`: Ruff, strict mypy (126 files), unit/contract (927 passed, 2 skipped), smoke, and full
offline suite (1,231 passed, 5 skipped). Exact-candidate Windows package build/install and
release-check passed, including benchmark thresholds and fresh deterministic paired evaluation; logs
and SHA-256 artifact evidence are under `out/live-agentic/release-candidate-9d28dc4/` and
`out/live-agentic/final-gates-candidate-9d28dc4/`. Hosted platform evidence, live scenario runs,
branch-protection verification, and provider billing verification remain open.

Planning-deliverable checks: all local Markdown links in the five changed documents resolve;
explicit source/test paths checked by the plan audit exist; `git diff --check` passed.
`graphify update .` completed its AST rebuild (4,787 nodes, 13,693 edges). It warned that 14 JSON
source/fixture files yielded no nodes and that documentation semantic updates require a separate
workflow. No semantic completeness or newly indexed plan content is claimed from that AST update.
