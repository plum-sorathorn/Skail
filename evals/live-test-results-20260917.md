# Live Test Results — 2026-09-17 / commit 6e9807f

> Isolation: worktree `Skail-live-20260917-133628` (branch
> `chore/live-probe-20260917-133628`), scratch fixture
> `%TEMP%\skail-live\fixture-20260917-133628`. No live agent ran with the
> primary checkout as workspace. No key is recorded in this file.

## Environment
- Commit/worktree/fixture commit: `6e9807f` /
  `C:\Users\plum\Documents\Works\Skail-live-20260917-133628` (removed on
  teardown) / fixture baseline `b97cd12` (`chore(live-probe): baseline fixture`)
- Python / skail-harness / Windows / terminal: Python 3.14.6 /
  skail-harness 0.1.0 (editable install at repo) / win32 / PowerShell
  (non-interactive probe harness)
- CPU/RAM/power/network: not captured (manual probe station; follow-up should
  record per Performance Protocol)
- Candidate model IDs and catalog revision: live `/v1/models` returned
  128 rows on 2026-09-17. Pinned candidates confirmed present:
  `openai/gpt-5-nano`, `google/gemini-2.5-flash-lite`, `openai/gpt-4.1-nano`,
  `openai/gpt-4.1-mini`, `glm-5.3-flash` (id `glm-5.3-flash`), `qwen-flash`.
- Discovered prices and substitutions: no substitutions needed; all plan IDs
  present. Observed (per 1M tokens, prompt/completion):
  - `openai/gpt-5-nano`: $0.05 / $0.40 — matches plan
  - `google/gemini-2.5-flash-lite`: $0.10 / $0.40 — matches plan
  - `openai/gpt-4.1-nano`: $0.10 / $0.40 — matches plan
  - `openai/gpt-4.1-mini`: $0.40 / $1.60 — matches plan (id confirmed as
    `gpt-4.1-mini`, no `openai/` prefix in catalog row id; CLI pin form
    `llmgateway:openai/gpt-4.1-mini` per plan convention)
  - `glm-5.3-flash`: $0.088 / $0.25 — matches plan envelope
  - `qwen-flash`: $0.05 / $0.40 — matches plan
  - All within admission envelope ($1.00/M in, $4.00/M out). No price rejection.
- Config hash (sanitized): default layered config, no `[providers.llmgateway]`
  entry (this is the P1 blocker — see Defects). `skail config show` shows
  `providers: {}`, `catalog: {entries: []}`, routing auto, max_agents 3,
  workspace shared.

## Dry run (required gate — PASS)
- `python scripts\smoke.py --fake-provider` → `Skail fake-provider smoke: ok`
  (exit 0)
- `python -m skail smoke --fake-provider` → ok (exit 0)
- `pytest tests\unit\test_performance.py tests\contract\test_llmgateway.py -q`
  → 25 passed
- `pytest tests\integration\test_assignment.py
  tests\integration\test_delegation_controls.py -q` → 40 passed
- Auth: `.env` `DEVPASS_KEY` present (length-checked only, never printed).
  Mapped to `LLMGATEWAY_API_KEY` in-process: `skail auth status` →
  `LLMGATEWAY_API_KEY: CONFIGURED`; `skail auth check` → exit 0,
  `Credentials detected for: LLMGATEWAY_API_KEY`. Note: plan names
  `DEVPASS_KEY` as the provider env var; this checkout only recognises
  `LLMGATEWAY_API_KEY`/`OPENAI_API_KEY`/`ANTHROPIC_API_KEY` (see Defects).

## Budget ledger
| Probe | Calls | Est. cost | Provider actual | Reserved after | Cumulative upper bound |
|---|---:|---:|---:|---:|---:|
| catalog discovery (`GET /models`) | 0 charged | $0.00 | $0.00 | n/a | $0.00 |
| P1 print-mode `llmgateway:openai/gpt-5-nano` | 0 (rejected pre-call) | $0.00 | $0.00 | $0.00 | $0.00 |
| P2–P7 | 0 (BLOCKED, same root cause) | $0.00 | $0.00 | $0.00 | $0.00 |
| **Campaign total** | **0 charged calls** | **$0.00** | **$0.00** | — | **$0.00 < $13.50 kill-switch, < $15.00 cap** |

Kill-switch was never approached. No retry consumed. No charged call made.

## Probe result
| ID | Mode | Route/assignment IDs | Attempts/peak children | TTFT/E2E | Outcome | Checks | Evidence path |
|---|---|---|---:|---:|---|---|---|
| P1 | `-p --no-session --budget 0.25 --max-agents 1 --lead-model llmgateway:openai/gpt-5-nano` | none (rejected) | 0/0 | n/a / 3.6 s to clean error | FAIL (harness config, pre-call) | exact-answer, delegation, assignment checks N/A — no call issued | stderr below (sanitized), no log retained with secrets |
| P2 | — | — | — | — | BLOCKED (same root cause as P1; not attempted to avoid repeat spend/failure loop) | — | — |
| P3 | — | — | — | — | BLOCKED (same) | — | — |
| P4 | — | — | — | — | BLOCKED (same) | — | — |
| P5 | — | — | — | — | BLOCKED (same) | — | — |
| P6 | — | — | — | — | BLOCKED (same; incl. TUI variant not run) | — | — |
| P7 | — | — | — | — | BLOCKED (same; adversarial probe deliberately not forced past config gate) | — | — |
| TUI smoke (P1/P6/P7 interactive) | — | — | — | — | NOT RUN (blocked on same config gate; no non-interactive TUI harness invoked) | — | — |
| Cancel/resume probe | — | — | — | — | NOT RUN (no live session to interrupt) | — | — |

P1 stderr (full, redacted — no key material):
`Provider configuration error: llmgateway: model is absent from the configured catalog`
exit 1, E2E 3.6 s.

## Performance
| Metric | Samples | Median | p95/max | Threshold | Result |
|---|---:|---:|---:|---:|---|
| Warm `skail --help` | 2 | ~1.0 s | ~1.01 s max | pass ≤0.75 / warn ≤1.25 | WARN (over pass, within warn) |
| Cold `skail --help` | 0 | — | — | pass ≤1.50 / warn ≤2.50 | NOT MEASURED |
| Warm TUI first paint / input-ready | 0 | — | — | pass ≤1.0/1.5 | NOT MEASURED |
| Live P1 TTFT / E2E | 0 live calls | — | — | TTFT p95 ≤10 s, E2E p95 ≤30 s | NOT MEASURED (no live call issued) |

No 10-sample startup batch or 3–5× P1 repeat was run: with zero live calls
possible, repeating the deterministic config rejection would not measure
provider latency.

## Safety/invariant evidence
- Assignment stickiness: no live assignment issued; nothing to reconcile.
  Deterministic gate (`test_assignment.py`) passes offline (40 tests).
- Maximum child attempts / peak concurrency: 0 children live; no violation
  possible. Delegation-control gate passes offline.
- Writer lease/worktree isolation: fixture scratch repo created outside the
  primary checkout and never presented to any live agent (no live agent ran).
  Primary checkout `git status` clean apart from pre-existing untracked
  (`evals/live-test-plan.md`, `package.json`, `.skail/`) plus this results file
  and removed temp scripts.
- Approval/trust decisions: not exercised live (no session).
- Secret/canary scan (FOUND/NOT FOUND only): NOT FOUND for both canary pattern
  and key material in retained artifacts. Key was mapped to
  `LLMGATEWAY_API_KEY` in-process only, never echoed, never written to a file,
  never placed on a command line; all captured output passed through a
  redaction filter before display. No journals/exports were produced by live
  runs (nothing to scan beyond this report).
- Session resume/export reconciliation: not exercised live (no session).

## Defects
| Severity | Reproduction | Expected | Actual | Session/run/event IDs | Sanitized evidence |
|---|---|---|---|---|---|
| Functional fail (blocks all live probes) | `python -m skail --no-session -p --budget 0.25 --max-agents 1 --lead-model llmgateway:openai/gpt-5-nano "Reply…"` with `LLMGATEWAY_API_KEY` set in-process | Manual pin accepted (model present in live catalog) and a charged call issued or a clear missing-provider-config hint | `Provider configuration error: llmgateway: model is absent from the configured catalog`, exit 1, zero calls | n/a (pre-call rejection) | stderr line above; `skail models list` shows only `fake:*` models; `skail config show` shows `providers: {}` |
| Doc/config gap | Plan §Setup says `api_key_env = "DEVPASS_KEY"` and `skail auth check` reads `DEVPASS_KEY` | Key from `.env` works as documented | `auth check` reports `No provider credentials configured` unless the key is exported as `LLMGATEWAY_API_KEY`; `auth status` only lists `LLMGATEWAY_API_KEY`/`DEVPASS_TOKEN`/`OPENAI_API_KEY`/`ANTHROPIC_API_KEY` | n/a | `auth check` output before/after mapping |
| Open plan Q2 unresolved | Plan asks for the config syntax to mark discovered catalog metadata trusted | A documented user-config snippet wiring `[providers.llmgateway]` + allowlisted models + trusted catalog entries | No example found in `config show --help`/models output during probe; per STOP rules no further grep sweep was run | n/a | — |

## Verdict
- PASS / CONDITIONAL PASS / FAIL: **FAIL (harness-side config gate; no model
  or provider fault)** — dry-run gates pass, catalog/pricing validated, spend
  $0.00, no safety violation, but P1–P7 have no live evidence because the CLI
  requires an explicit `[providers.llmgateway]` + catalog allowlist that was
  not wired during this run. Per task constraints the run was recorded as
  FAIL-with-logs rather than looped.
- Total live cost (larger of actual/estimate): **$0.00**.
- Unresolved warnings: warm `--help` ~1.0 s (WARN band); TUI/perf matrix,
  approval/trust, resume/export, and fault-injection companions unmeasured
  live (covered only by offline suites listed above).

## Follow-ups
1. Provide the supported user-config snippet for `[providers.llmgateway]`
   (`type`, `base_url = "https://api.llmgateway.io/v1"`,
   `api_key_env = "LLMGATEWAY_API_KEY"`, `models = [...]`) plus the trusted-
   catalog entry path (plan open Q2), then re-run P1 pinned before the rest.
2. Decide whether `DEVPASS_KEY` should be an accepted `api_key_env`/auth alias
   or the plan updated to `LLMGATEWAY_API_KEY` mapping.
3. Re-run only affected probes after the config fix; the single full-suite
   retry allowance and the <$15 ceiling remain entirely unconsumed.
4. Capture the full Performance Protocol matrix (10× startup, TUI paint,
   TTFT/E2E splits) once live calls flow.

## Teardown
- Temp probe scripts (`scripts/live-*-tmp.*`) removed from the checkout.
- Scratch fixture and worktree removed; branch deleted.
- No live journals/exports retained; this sanitized report is the only new
  committed artifact. `$env:DEVPASS_KEY` was never set persistently;
  in-process `LLMGATEWAY_API_KEY` copies died with their probe processes.
