# S8 natural escalation diagnosis — 2026-09-28 local time

S8 remains **failed/incomplete**. The historical run genuinely exercised a first child failure, but
it did not execute or integrate a stronger second attempt. A new paid run is not qualified while
the authenticated catalog contains no automatically eligible model. Selecting accessible model
names does not supply the trusted capability evidence required by the retry contract.

## Historical observations

- Acceptance: [live test plan](live-agentic-test-plan.md#s8--natural-escalation-only). The disposable
  fixture's `tests/test_parser.py::test_parse_records_ignores_blank_lines_and_splits_once` failed
  at baseline with `NotImplementedError`; a failure must arise naturally, keep one task identity,
  and permit at most one stronger retry. An accepted result must integrate before an independent
  focused test can count as a pass.
- Schema-v2 export: `out/live-agentic/session-S8-retest-2026-09-26-final.json`. Session
  `58b8533a-d99b-4acd-bcc5-adcccd86a78a`, run `14913447-a527-452f-93b6-f83de65ce04b`,
  task `f4dd996c-fb76-4914-8a2d-a11c42a248c7`. The Qwen3.8 Flash first attempt
  `385fab9f-0fab-468d-a48c-cf286082aaa4` reached a real child model call and failed
  `result_validation` at `$.artifacts.0.kind` (event sequence 133). This is a malformed child
  result, not a demonstrated parser-code failure. The isolated worktree's parser tests passed
  3/3, but the result was never accepted or integrated; the parent fixture stayed unchanged.
- The same task received one second attempt ID `92784a58-a5cf-4a73-bfb2-64a7e174ce1e`.
  Event sequence 135 reports `routing_ineligible` / `model_disabled`. No second assignment or
  provider call appears. The first assignment's routing-input snapshot contained 142 models:
  139 disabled and three enabled (`gpt-4.1`, `gpt-4.1-mini`, `qwen3.8-flash`). It is **not** a
  snapshot of the later failed retry. Its enabled GPT models make the exported aggregate reason
  insufficient to conclude that those specific alternatives were disabled at retry time.
- The 25 historical calls cost USD 0.024644374 in the in-house ledger and were already audited.
  Provider billing remains unknown. No new inference calls or cost rows were added here.

## Routing diagnosis

`RunController` pins the configured child model for attempt one, but retry two excludes the failed
model, raises the implementer floor to 0.65 in auto mode, and calls `AssignmentService.assign`.
`select_model` rejects automatically routed profiles without trusted capability evidence before
checking the floor. The historical retry's `model_disabled` reason was not an individual model
diagnosis: the selector chose the most numerous exclusion across the whole catalog. The 139
disabled candidates in the earlier assignment could have hidden `auto_ineligible` on usable
alternatives. The exact retry candidate snapshot was not persisted, so its per-model exclusions
cannot be reconstructed as observations. This limitation is separate from the first child result
error.

The read-only authenticated refresh in
`out/live-agentic/s8-diagnosis-20260928/catalog-qualification.json` returned 143 accessible models
at `2026-09-29T03:37:34Z` and **zero automatically eligible models**. The user-authorized candidate
list was GPT-4.1, GPT-4.1-mini, and Qwen3.8 Flash. Each is accessible, has current catalog price,
and advertises tool and structured-output support; each lacks a trusted capability vector. The
snapshot does not establish a 0.65 fit for any model. Manual selection permits a first attempt,
but S8's same-task escalation uses auto routing, so a selected list cannot make attempt two pass.
No quality score was inferred from model names, prices, or isolated outcomes.

## Diagnostic repair and remaining work

The selector now gives the blocking reason among configured, healthy, enabled, non-excluded
candidates precedence over catalog-wide disabled counts. A red/green regression shaped like the
S8 retry proves `auto_ineligible` is reported when disabled catalog entries outnumber the enabled
manual-only alternative. Candidate eligibility, budgets, exclusions, and model selection are
unchanged; this repairs the route explanation only.

To qualify a new S8 live attempt, obtain replayable trusted capability evidence for at least one
accessible, price-current alternative meeting the escalated 0.65 implementer floor and required
tools/structured output, then confirm that the first-attempt model and alternative are distinct,
the run can reserve both attempts within the remaining S8 allocation, and the fixture has a
natural failing focused test. If no such evidence exists, retain S8 as failed/incomplete and make
no paid retry. Once qualified, inspect both attempt IDs, failure handoff, second route and provider
call, accepted child result, integration, parent diff, independent focused test, and reconciled
per-call costs. Persist a safe attempt-keyed failure reason and retry candidate exclusions in a
future diagnostic change; the current export does not contain that detail. Do not weaken the
`TaskResult` schema or manufacture the first failure.

## Verification

The regression failed before the selector repair (`model_disabled` instead of
`auto_ineligible`) and passed after it. Focused selector/assignment tests passed 48/48.
Ordered gates passed on the changed source: Ruff, strict mypy (126 source files), unit/contract
928 passed and 2 skipped, smoke, full offline suite 1,232 passed and 5 skipped. Gate logs are
preserved under `out/live-agentic/s8-diagnosis-20260928/01-ruff.log` through `05-full-suite.log`.
No live S8 pass is claimed from these offline results.
