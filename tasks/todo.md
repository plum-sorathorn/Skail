# Remaining remediation execution checklist

## Presentation acceptance (2026-09-30)

Fresh real-TUI S1, S2, and two-model S3 runs completed. S1 and S3 left their fixtures unchanged;
S2 changed only the named normalization source/test and passed the independent focused tests 3/3
after its baseline failed 1/1. A no-call resume captured the previously completed S6 answer.
All five final answers matched the mounted Textual renderer exactly and had answer fragments in
terminal captures. Evidence: `out/live-agentic/presentation-live-20260930/` and its
`live-presentation-comparison.json`. The earlier historical export replay remains under
`out/live-agentic/presentation-replay-20260930/`. The first S3 repeat blocked on decision admission;
the first S2 run was cancelled after an out-of-scope `tests/__init__.py` write. Both are preserved
as failed attempts. Thirty-two fully priced new calls cost USD 0.020565800 locally, including
those failures; the append-only audit now has 925 unique IDs and the campaign estimate is
USD 3.978118284. Provider billing remains unknown.

## Attempt diagnostics and offline gates (2026-09-30)

Terminal child results now retain safe failure reason codes by attempt ID, including when a stronger
retry succeeds. Session exports attach those codes to the corresponding attempt rows without raw
provider output. Focused regressions passed 21/21. The ordered combined-candidate gates passed:
Ruff, strict mypy (126 files), unit/contract 941 passed with 2 skipped, smoke, and full offline suite
1,252 passed with 5 skipped. The subsequent local release renewal is recorded below.

## Exact-candidate local release and speed evidence (2026-09-30)

Clean isolated candidate `557b3fc2fe2338c948c8fada1bae541c595a20d9` matched the 26 changed
working-tree files by line content when frozen. Package build, isolated wheel install, and all eight
release-check stages passed, including the full suite, benchmark thresholds, and fresh paired
evaluation. The wheel SHA-256 is `24962cb9b3f163206218a0c6e613f04ee960d006db041d9ede5cceddb5f59e08`;
sdist SHA-256 is `2abb5989b87814f1c399ab62438fab40561647e34d924f9ed172c132b0ceb0e4`.
Evidence, retained artifacts, 54-fixture/2,700-result evaluation, and three timing logs are in
`out/live-agentic/release-renewal-20260930/`. The exact-candidate serial suite wall times were
238.548, 210.763, and 237.399 seconds (median 237.399); 1,252 passed and 5 skipped in each run.
The 131.336-second objective remains unmet. Hosted matrix and branch protection remain unverified;
GitHub CLI is unauthenticated in this workspace.

## S8 live pass (2026-09-29, current)

[S8 resolution](s8-resolution-2026-09-29.md) closes R5 and R10-S8: natural GPT-4.1 nano failure,
same-task selected GPT-5 mini retry, accepted integration, independent parser test 1/1. New local
cost USD 0.011183000 including three probes; campaign estimate USD 3.957552484. Prior failed runs
and unrelated open gates below retain their historical/separate status.

## S8 diagnosis update (2026-09-28, historical)

[The S8 diagnosis](s8-diagnosis-2026-09-28.md) confirms a natural first child result-validation
failure at `$.artifacts.0.kind`, followed by a same-task retry rejected before a provider call.
The exported `model_disabled` was an aggregate binding reason; the earlier snapshot's 139 disabled
entries could dominate it, and it did not identify a disabled GPT alternative. A fresh authenticated
read-only catalog refresh found 143 accessible models and zero auto-eligible models, including no trusted capability vector
for GPT-4.1, GPT-4.1-mini, or Qwen3.8 Flash. A red/green regression now makes the route explanation
prioritize the actionable `auto_ineligible` reason among enabled alternatives. No new inference
calls were made. S8 remains failed/incomplete, and R5/R10-S8 stay unchecked until trusted evidence
qualifies a genuine stronger auto retry and a live run passes integration and independent testing.
Ordered gates on this routing-explanation change passed: Ruff, strict mypy (126 files), unit/contract
928 passed with 2 skipped, smoke, and full offline suite 1,232 passed with 5 skipped. Earlier S5
gate counts below refer to the prior source commit. Campaign local estimate remains USD 3.946369484, excluding
historical unknowns; provider billing is unknown.

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


Authoritative detail, dependencies, evidence, and acceptance: [plan.md](plan.md).
Baseline: `9f9d1c9ed19b8ad63feea77f0bbc04feef847c55`. Earlier source commit `6a99a32` passed the
ordered offline gates and package-check; clean-worktree release-check passed on `4f0b342`. S4, S6,
the separate live child-scope denial, and the R9
active-child cancellation pass. S5 passes its main live path and S8 passed on September 29; presentation/speed/
R9 conditional edges/hosted release evidence remain open. Current local campaign estimate is
USD 3.957552484; provider billing is unknown.

- [x] R0: Reconcile existing provider-call IDs and freeze the current local cost/evidence baseline.
- [x] R1: Correct Ctrl+C test ordering; prove shutdown while mounted and restore with fresh stores.
- [x] R2: Reproduce and fix exhausted decision completion on initial and resumed paths.
- [x] R3: Validate direct/read/write plan examples and mode-appropriate safe repair guidance.
- [x] Checkpoint A: Focused question/resume/decision contracts pass without extra work or calls.
- [x] R4a: Deliver complete child result guidance through the actual assembled agent.
- [x] R4b: Resolve scoped-child digest/test capability through an authentic digest tool and operator test path
  without opening a command escape or calling a file hash a passed test.
- [x] R5: Qualified the selected three-model roster with reviewed capability profiles, fresh gateway
  pricing and a 0.75 USD run cap; GPT-5 mini clears the 0.65 retry floor and strictly improves fit.
  Evidence: `out/live-agentic/s8-fix-20260929/verification.json` and `reviewed-profiles.json`.
- [x] R6: Reproduce dirty-worktree retry and preserve authenticated same-task work across attempts.
- [x] R7a: Prove exactly two isolated writers, accepted results, checkpoint revision, integration, FIFO.
- [x] R7b: Prove two explorers -> checkpoint/revision -> scoped implementation offline and live;
  independent 4/4 parser tests and mounted plan replay matched the fresh live journal.
- [x] Checkpoint B: Writer/adaptive/retry paths pass offline; live qualification is independently recorded.
- [x] R8: Render persisted final answers exactly once across live return, event replay, and restart.
- [x] R9-offline: Verify question-mode 80x24 focus/visibility, pending-question refusal, transient
  queue disposal, canceled-plan ownership, non-TTY guards, admission failure, and unlaunched-node
  terminalization.
- [x] R9-live-cancel: A real TUI run cancelled while two child model calls were active. The run,
  child tasks/attempts, plan nodes, and reservations terminalized; the queued follow-up was visible
  and discarded, with no provider start after cancellation, traceback, unawaited warning, or fixture change.
- [ ] R9-live-edges: S6 fixed-choice question interaction was observed; live free-form question,
  permission Approve/Reject, nested delegation, and other conditional lifecycle edges remain
  unobserved unless a matching natural operation occurs.
- [x] R10-S6: Same durable run restored the question, accepted JSON, implemented the exporter/test,
  and passed the independent focused check. Its durable answer now also matches a no-call resumed
  TUI capture and the mounted renderer.
- [x] R10-S4: Both live results were accepted/integrated; the checkpoint and FIFO completed; child
  interval overlap was observed; independent parser/report/integration tests passed 3/3.
- [x] R10-child-denial: A child-owned out-of-scope `write_file` was denied; the parent fixture and
  isolated workspace contain no out-of-scope test file. This is separate from S7's lead traversal.
- [x] R10-S5: Qualified manual run accepted both discoveries, revised the plan, integrated the scoped
  implementation, passed independent parser tests 4/4, and matched mounted plan replay.
- [x] R10-S8: Natural first-attempt result-validation failure followed by same-task stronger retry,
  accepted integration, selected-roster audit and independent parser test 1/1 on September 29.
- [x] R10-presentation: Fresh S1/S2 and both S3 model answers matched exported completion events,
  mounted TUI rendering, and terminal captures; the existing S6 answer matched on no-call resume.
- [ ] R10-edges: Attach matching R9 live evidence; keep conditional permission/nested-delegation and
  unobserved transitions open unless separately justified by the accepted verification contract.
- [x] Checkpoint C: S4/S6 and child-denial outcomes match their exports, fixture diffs, independent
  tests, and reconciled costs. S5/S8 and other open criteria retain their separate dispositions.
- [x] R11: Three controlled current-candidate external-wall runs; preserve all independent test boundaries.
- [ ] R11-speed: Meet the original 20% objective (131.336-second median versus 164.17 baseline).
  The new exact-candidate median is 237.399 seconds across three serial passes, 106.063 seconds
  above target. The previous 153.587-second series is historical; no safe causal optimization is
  established and no independent test boundary was removed.
- [x] R12: Reconcile LIVE-001–045, OUT-001–016, new findings, old unchecked items, and changed docs.
- [x] R13: Final-revision Ruff -> mypy -> unit/contract -> smoke -> full offline suite; Graphify/diff review.
- [x] R14-local: Package build/install and clean-worktree release-check passed on code candidate
  `6a99a32` / documentation commit `4f0b342`. Wheel SHA-256 `64d823546ce4696a450c445376c394f7072eabc68f10a2b41fea60c78d262c95`;
  sdist SHA-256 `ec2ab8c425489ff35af04219a408f8c318e3f38a2c7c0966c240484aebf8216e`. This is historical
  evidence; the later S5/S8 changes were renewed on candidate `557b3fc` below.
  Hosted external gates remain separate.
- [ ] R14-external: Exact-candidate hosted Windows/Linux matrix, Python 3.12–3.14 fast-matrix evidence,
  and branch-protection required-check verification.
- [x] R14-renewal: Package/release checks passed on clean isolated candidate `557b3fc`, including
  benchmark thresholds and a fresh complete paired evaluation. Artifact hashes and raw retained
  reports are in `out/live-agentic/release-renewal-20260930/`.
- [x] Diagnostic follow-up: Retain safe attempt-keyed child failure reason codes through retry
  terminalization and export. The first failure survives a successful second attempt; exported
  codes are allowlisted and raw provider output is excluded.
- [x] Checkpoint D: The disposition below separates passed, failed, unexercised, withheld, and
  external-unknown items. Release readiness remains withheld.

Current dispositions: S4, S6, S7 lead traversal, separate child-scope denial, and R9 active-child
cancellation passed their stated
criteria. S5 main live path, S8, and S1/S2/S3/S6 presentation passed. Conditional R9 permission,
free-form question, and nested-delegation edges, the 20% speed objective, and hosted/branch-protection
evidence remain open. Provider
billing is unknown.

Checkpoint D disposition: **Passed** — S4, S5 main path, S6, S7 lead traversal, separate child
scope denial, S8, R9 live cancellation, ordered offline gates, and local package/release checks.
**Failed objective** — the 20% serial suite speed target. The first S3 presentation repeat blocked
and the first S2 repeat wrote out of scope; both are preserved and superseded by passing fresh runs.
**Unexercised** — conditional live permission, free-form question, and nested-delegation transitions.
**Withheld** — release readiness while the speed objective and external gates remain open.
**External unknown** — exact-candidate hosted Windows/Linux and Python 3.12–3.14 matrix, branch
protection settings, and provider billing. These open criteria withhold release readiness.
