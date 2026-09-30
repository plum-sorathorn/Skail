# S8 selected-model escalation — passed live

S8 passed in the real interactive TUI on 2026-09-29. This supersedes the current acceptance status
in the [September 28 diagnosis](s8-diagnosis-2026-09-28.md); historical failed runs remain failed.

## Diagnosis and changes

The historical first child returned malformed result evidence. Its automatic retry had no trusted
capability profiles among the enabled models. The catalog-wide `model_disabled` aggregate obscured
that cause; the earlier diagnostic repair correctly addressed that explanation only.

Two additional defects were reproduced and fixed:

- CLI bootstrap constructed candidates from every discovered model without honoring the saved
  selected list. It now enables only configured selections and explicit run pins, even when the
  selected list is empty or has no catalog matches. Discovery remains available to the picker.
- Raising a task floor did not guarantee a model stronger than the failed model. The selector now
  requires strictly greater capability fit, using a baseline persisted with the first assignment.
  Unknown baselines fail closed. Manual-mode first attempts use automatic routing for escalation.

The first failure, maximum two child attempts, result validation, scoped writes, remaining-budget
checks, failure handoff, and integration validation remain runtime-owned.

## Qualified models

The isolated run selected exactly `llmgateway:gpt-4.1-nano`, `llmgateway:gpt-4.1-mini`, and
`llmgateway:gpt-5-mini`. Authenticated discovery found all three. Discovery alone still supplies
no capability scores, so this run used explicit user catalog entries with reviewed provenance.

The capability estimates use the same published benchmarks for all three models, divided by 100:

| Model | Coding: Aider polyglot | Reasoning: GPQA diamond | Tool reliability: tau2 retail |
|---|---:|---:|---:|
| GPT-4.1 nano | 0.062 | 0.503 | 0.215 |
| GPT-4.1 mini | 0.316 | 0.650 | 0.660 |
| GPT-5 mini | 0.716 | 0.823 | 0.783 |

Source: [OpenAI's published benchmark table](https://openai.com/index/introducing-gpt-5-for-developers/),
reviewed September 29. These are routing estimates, not a local benchmark reproduction. Published
GPT-5 results use high reasoning; this runtime uses the provider default. Latency is separately
measured by one small request per model and normalized as `min(seconds / 60, 1)`; it is not inferred
from model names. Pricing comes from fresh gateway discovery. No model gains eligibility merely
because it is expensive or accessible. Profiles/configuration are preserved with the live evidence;
they were applied to the isolated test home, not installed globally for every provider/model.

## Live evidence

Directory: `out/live-agentic/s8-fix-20260929/`.

- Session: `bcefbee6-e8da-4f22-9516-adf9cd422813`.
- Run: `6e929683-31ff-49e9-b69d-7e1c76d269ec`.
- Child task: `f59da161-1d65-46a0-82c0-bb6af60c7c49`.
- Original fixture baseline: `113ed8c9f69b0b6dfca596b0dc86052d3b63dc3a`; the existing parser test
  failed with `NotImplementedError` before the run. No failure was manufactured.
- First attempt: `fd441a1b-967a-4881-bbba-6d28e059f2a3`, GPT-4.1 nano, recorded fit 0.062;
  naturally failed `result_validation` at `$.verification.0.evidence_ref`.
- Retry: `692ada8a-9449-452b-9efd-22c3c2eaa4b0`, GPT-5 mini, recorded fit 0.716, floor 0.65;
  same task, new assignment, retained workspace and recorded failure-handoff packet.
- Accepted retry integrated changeset `4dc19349-371d-40fc-b6d6-22ebc2eec4e9`. The only tracked
  changed path was `src/live_fixture/parser.py`; the independent original parser test passed 1/1.
- Sixteen completed provider calls all used the selected roster. Every cost recomputed exactly
  from frozen journal rates. Reservations are settled/released. Run cost: USD 0.010993400.
  Three separate latency probes cost USD 0.000189600; total new cost USD 0.011183000.
  Campaign local estimate after append-only reconciliation: USD 3.957552484. Provider billing unknown.

`verification.json` records assertions from the export and live journal, model eligibility,
assignment/attempt identity, failure handoff, integration, independent test, and cost checks.
`final-session-export.json`, `reviewed-profiles.json`, `latency-probes.json`, `baseline-test.log`,
`operator-parser-tests.log`, and `tui-transcript-final.txt` preserve the underlying observations.
`CALL_COST_AUDIT.csv` includes the 16 run call IDs. Probe receipts have no invented journal IDs.

## Regression verification

Tests cover the selected startup roster, missing/empty selections, equal/weaker/unknown capability,
disabled stronger models, budget and tool constraints, a forged lower baseline hint, removal of the
failed model from a later catalog, and preserved worktrees in auto/manual retry paths.
The live pass qualifies S8, not unrelated release, timing, or presentation acceptance items.

Final ordered gates passed on the completed change: Ruff; strict mypy (126 source files);
unit/contract 941 passed, 2 skipped; offline smoke; full offline suite 1,250 passed, 5 skipped.
The skips are the existing opt-in/environment gates. `offline-gates.json` and `01-ruff.log` through
`05-full-suite.log` in the evidence directory record commands, timestamps, exit codes and output.
Graphify's code graph was refreshed, local document links resolve, and `git diff --check HEAD`
passed. Package/release/hosted checks were not part of this S8 repair.
