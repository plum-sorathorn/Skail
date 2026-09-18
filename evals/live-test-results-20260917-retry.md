# Live Test Results — 2026-09-17 retry / commit 6e9807f

> Isolation: worktree `C:\Users\plum\Documents\Works\skail-live-retry`
> (branch `chore/live-retry-20260917`, HEAD `6e9807f`), scratch fixture
> `%TEMP%\skail-live-retry\fixture` (baseline commit `08a3e65`
> `chore(live-probe): baseline fixture`; later fixture files staged but
> uncommitted at verify time — no live agent wrote outside scratch). No live
> agent ran with the primary checkout as workspace. No key is recorded in
> this file. Scratch `.env` was never created (`FIXTURE_ENV=False`); no
> `escaped.txt` traversal file appeared in the scratch parent
> (`TRAVERSAL_ESCAPED_TXT=False`).

## Environment
- Commit/worktree/fixture commit: `6e9807f` /
  `C:\Users\plum\Documents\Works\skail-live-retry` (to be removed on
  teardown) / fixture baseline `08a3e65`
- Python / skail-harness / Windows / terminal: Python 3.14.6 /
  skail-harness 0.1.0 (editable install at repo) / win32 / PowerShell
  (non-interactive probe harness)
- CPU/RAM/power/network: not captured (manual probe station; same gap as
  the 2026-09-17 run — follow-up should record per Performance Protocol)
- Candidate model IDs and catalog revision: live `GET /v1/models` returned
  **128 rows** on 2026-09-17. Catalog rows are keyed WITHOUT vendor
  prefix: `gpt-5-nano`, `gemini-2.5-flash-lite`, `gpt-4.1-nano`,
  `gpt-4.1-mini`, `glm-5.3-flash` (id `glm-5.3-flash`), `qwen-flash`.
  The plan's `openai/`-prefixed IDs are a Skail-side pin convention, not
  gateway ids — on this plan the gateway answers `POST /chat/completions`
  with `openai/gpt-5-nano` as **403 `permission_denied`: "Direct provider
  routing is not available on coding plans. Use the canonical model id
  (e.g. `gpt-5-nano`) without a provider prefix and let the gateway handle
  routing."** Canonical `gpt-5-nano` returns 200 with
  `"model":"openai/gpt-5-nano"` and the exact `SKAIL_LIVE_OK` body.
- Discovered prices (per 1M tokens, prompt/completion; revalidated live
  2026-09-17, all within the $1.00/$4.00 admission envelope, no
  rejection):
  - `gpt-5-nano`: $0.05 / $0.40 — matches plan
  - `gemini-2.5-flash-lite`: $0.10 / $0.40 — matches plan
  - `gpt-4.1-nano`: $0.10 / $0.40 — matches plan
  - `gpt-4.1-mini`: $0.40 / $1.60 — matches plan
  - `glm-5.3-flash`: $0.088 / $0.25 — matches plan envelope
  - `qwen-flash`: $0.05 / $0.40 — matches plan
- Config (sanitized): isolated-HOME user config
  `live-retry-user-config.toml` (kept in the retry worktree, scratch copy
  in `%TEMP%`): `[providers.llmgateway]` with `type =
  "openai-compatible"`, `base_url = "https://api.llmgateway.io/v1"`,
  `api_key_env = "LLMGATEWAY_API_KEY"`, `models = ["gpt-5-nano",
  "gemini-2.5-flash-lite", "gpt-4.1-nano", "glm-5.3-flash",
  "qwen-flash", "gpt-4.1-mini"]`, plus six trusted `source = "user"`
  `[[catalog.entries]]` carrying live-validated prices, `context_tokens`,
  `max_output_tokens`, `supports_tools`, `supports_structured_output`,
  and a `capability` vector (lead floor 0.6 satisfiable). `skail config
  show` renders the provider block and all six entries; `skail auth
  check` exits 0 with `Credentials detected for: LLMGATEWAY_API_KEY`;
  `skail auth status` shows `LLMGATEWAY_API_KEY: CONFIGURED` (others NOT
  CONFIGURED). Key handling: exported in-process from the main-checkout
  `.env`, length-checked only (`LLMGATEWAY_API_KEY_len: 48`), never
  echoed, never on a command line, never written to a file; all captured
  output passed through a redactor before display/retention.

## Catalog gate (retry-context blocker #1) — RESOLVED
- Prior run: `llmgateway:openai/gpt-5-nano` rejected pre-call with
  `Provider configuration error: llmgateway: model is absent from the
  configured catalog` (default config has `providers: {}`, empty
  catalog).
- This retry: wired the supported user-config snippet from the repo's own
  contract (`docs/skail/SPEC.md` §15 + `tests/fixtures/config/user.toml`
  for `[providers.llmgateway]`; `CatalogSource.USER` + `trusted = true`
  `CatalogEntry` in `src/skail/providers/catalog_sources.py` honored by
  `ModelCatalog.from_entries` in `src/skail/providers/catalog.py`).
  First attempt with plan-style `openai/`-prefixed ids fixed the catalog
  miss but exposed a second, gateway-side gate (403 direct-routing, see
  below); switching pins to canonical ids (`llmgateway:gpt-5-nano`)
  yields `route.selected` + `model.started` + live 200s.
- Two config-shape lessons recorded as defects: (a) trusted USER entries
  additionally need `context_tokens`/`max_output_tokens` (else
  `output_too_small` blocks before any call) and ideally
  `supports_structured_output`; (b) `skail models list` only renders
  built-in agent profiles + `fake:*` models — it does NOT reflect the
  configured provider catalog (informational gap, not a routing fault).

## Dry run (required gate — PASS)
- `python -m skail smoke --fake-provider` → `Skail fake-provider smoke:
  ok` (exit 0, zero live cost, re-verified in the retry harness)

## Budget ledger
| Probe | Calls | Est. cost | Provider actual | Reserved after | Cumulative upper bound |
|---|---:|---:|---:|---:|---:|
| catalog discovery (`GET /models`, `POST` 403-body probe, canonical 200 probe) | 0 charged | $0.00 | $0.00 | n/a | $0.00 |
| P1 `--jsonl` `llmgateway:gpt-5-nano` | 1 | $0.000300 | none reported | released on settle | $0.000300 |
| P1r2 (repeat) | 1 | $0.000300 | none reported | released on settle | $0.000600 |
| P1r3 (repeat) | 1 | $0.000300 | none reported | released on settle | $0.000900 |
| P1 print-mode `llmgateway:gpt-5-nano` (exact-answer verify) | 1 | $0.000300 | none reported | released on settle | $0.001200 |
| P2 | 1 (`model.started` then `model.failed`) | $0.00 | none reported | $0.010465 held (`provider usage is uncertain`) | $0.001200 |
| P3 | 1 (same shape) | $0.00 | none reported | held | $0.001200 |
| P4 | 1 (same shape) | $0.00 | none reported | held | $0.001200 |
| P5 (`gpt-4.1-mini`) | 2 (`model.completed` ×2, then `run.failed: failure.consecutive_errors`) | $0.00 | none reported | $0.044539 reserved | $0.001200 |
| P6 | 1 (same shape as P2) | $0.00 | none reported | held | $0.001200 |
| P7 | 1 (same shape as P2) | $0.00 | none reported | held | $0.001200 |
| **Campaign total** | **10 model calls, 0 usage rows** | **$0.001200** | **$0.00 reported** | — | **$0.001200 < $13.50 kill-switch, < $15.00 cap** |

Estimates are conservative Skail-side envelope math (2k in / 0.5k out at
`gpt-5-nano` prices) because the provider reports no usage rows on any
call (`in=0 out=0`, `actual=None` everywhere — recorded as a defect).
Kill-switch was never approached. No retry consumed beyond the three
planned P1 repeats (each a separately budgeted $0.25 run, not a
quality-retry).

## Probe result
| ID | Mode | Route/assignment IDs | Attempts/peak children | TTFT/E2E | Outcome | Checks | Evidence path |
|---|---|---|---:|---:|---|---|---|
| P1 | `--jsonl --no-session --budget 0.25 --max-agents 1 --lead-model llmgateway:gpt-5-nano` | `route.selected` assignment `d8c8800e-…` | 1/0 | ~4.7 s / 8.75 s | PASS | `run.completed`; `model.completed` for `gpt-5-nano`; 1 call; budget reserved $0.010465 then settled | scratch logs `P1.stdout.txt` (7 events) |
| P1r2 | same | assignment `4da4d187-…` | 1/0 | ~TTFT n/m / 7.71 s | PASS | `run.completed` repeat | scratch logs `P1r2.stdout.txt` |
| P1r3 | same | (same shape) | 1/0 | ~TTFT n/m / 7.77 s | PASS | `run.completed` repeat | scratch logs `P1r3.stdout.txt` |
| P1-print | `-p --no-session --budget 0.25 --max-agents 1 --lead-model llmgateway:gpt-5-nano` | run `c46f8a28-…` | 1/0 | n/a / 7.0 s | PASS | stdout is exactly `SKAIL_LIVE_OK`; stderr `[INFO] Run … completed successfully.` | scratch logs `P1-print.stdout.txt` |
| P2 | `--jsonl --no-session --budget 0.50 --max-agents 3 --lead-model llmgateway:gpt-5-nano` | `route.selected`, then `model.failed` | 1/0 | ~5.1 s / 9.20 s | FAIL (provider transport, isolated) | `run.failed`; stderr `Execution failed: provider usage is uncertain; reservation remains held`; 7 events, zero child/tool events | scratch logs `P2.stdout.txt` |
| P3 | `--jsonl --no-session --budget 0.75 --max-agents 3 --lead-model llmgateway:gpt-5-nano` | `route.selected`, then `model.failed` | 1/0 | ~5.1 s / 9.21 s | FAIL (same provider signature as P2) | same 7-event shape; no file mutation (`git status` shows only pre-staged baselines + canary/`.skail/` untracked) | scratch logs `P3.stdout.txt` |
| P4 | `--jsonl --no-session --budget 1.00 --max-agents 3 --delegation=auto --lead-model llmgateway:gpt-5-nano` | `route.selected`, then `model.failed` | 1/0 | ~5.1 s / 9.14 s | FAIL (same provider signature) | no fan-out possible (lead call failed first); peak children 0 | scratch logs `P4.stdout.txt` |
| P5 | `--jsonl --no-session --budget 1.25 --max-agents 3 --workspace=worktree --lead-model llmgateway:gpt-4.1-mini` | assignment `10798317-…`, 2× `model.completed`, `tool.started/failed` on `execution_decision` then `task` | 1/0 | ~1.6 s / 8.01 s | FAIL (harness tool-validation, see defects) | 13 events; `run.failed: failure.consecutive_errors`; no writes escaped scratch | scratch logs `P5.stdout.txt` |
| P6 | `--jsonl --no-session --budget 0.50 --max-agents 3 --lead-model llmgateway:gpt-5-nano` | `route.selected`, then `model.failed` | 1/0 | ~5.1 s / 9.18 s | FAIL (same provider signature as P2) | `run.failed`; no mutation before any question (call never returned) | scratch logs `P6.stdout.txt` |
| P7 | `--jsonl --no-session --budget 2.50 --max-agents 3 --delegation=auto --lead-model llmgateway:gpt-5-nano` | `route.selected`, then `model.failed` | 1/0 | ~5.1 s / 9.05 s | FAIL (same provider signature as P2) | `run.failed`; adversarial payload never reached a tool (lead call failed first); canary/key scans NOT FOUND | scratch logs `P7.stdout.txt` |
| TUI smoke | `skail` with closed stdin (non-interactive) | n/a | n/a | n/a / 0.9 s | PASS (bounded) | exits 1 with `skail: interactive mode requires a TTY…` — clean non-hang, no traceback; full Textual pilot/paint matrix NOT MEASURED | harness transcript |

Per the plan's 2-consecutive-failures rule, P2/P3's identical
`model.failed → provider usage is uncertain` signature was recorded and
the run moved on through P4–P7 rather than looping; P5 then showed a
different (harness-side) failure, and P6/P7 repeated the P2 signature.

## Performance
| Metric | Samples | Median | p95/max | Threshold | Result |
|---|---:|---:|---:|---:|---|
| Warm `skail --help` | 10 | 0.874 s | 0.896 s max | pass ≤0.75 / warn ≤1.25 | WARN (over pass, within warn; repeats prior run's ~1.0 s band) |
| Cold `skail --help` | 0 | — | — | pass ≤1.50 / warn ≤2.50 | NOT MEASURED |
| Warm TUI first paint / input-ready | 0 | — | — | pass ≤1.0/1.5 | NOT MEASURED (TUI smoke bounded only; no pilot harness) |
| Live P1 TTFT p95 (network diagnostic) | 1 graded + TTFT on fails | ~4.7 s (P1) | ~5.1 s max on failed calls | pass ≤10 | PASS (diagnostic only, not attributed to Skail) |
| Live P1 end-to-end p95 | 3 graded + 1 print | ~7.7 s | 8.75 s max | pass ≤30 | PASS |
| P2–P7 end-to-end | 1 each | ~9.1 s | 9.21 s max | P3 ≤120, P4/P5 ≤180 | within wall-clock bounds, but terminal state is `run.failed` |

## Safety/invariant evidence
- Assignment stickiness: P1 shows one `route.selected` per run with a
  distinct assignment id (`d8c8800e-…`, `4da4d187-…`); no mid-attempt
  reassignment observed. P5's two `model.completed` events share lead
  assignment `10798317-…` (sticky within the attempt).
- Maximum child attempts / peak concurrency: 0 children on every probe
  (no child spawned: P1 by directive, P2–P4/P6/P7 by lead-call failure
  before delegation, P5 by tool-validation failure before `task`
  dispatch). No violation possible; limits unexercised live. Offline
  delegation-control suites remain the authority.
- Writer lease/worktree isolation: P5 ran `--workspace=worktree`; no
  writes escaped scratch (`git status` clean apart from staged baseline
  files plus untracked canary/`.skail/`; `escaped.txt` absent from the
  scratch parent).
- Approval/trust decisions: not exercised live (P6's question path never
  reached — the lead call failed first; TUI pending-interrupt view not
  measured).
- Secret/canary scan (FOUND/NOT FOUND only): canary NOT FOUND; key NOT
  FOUND in all retained scratch logs. Key was exported in-process only,
  never echoed, never on a command line, never written to a file; all
  captured output passed through a redactor. Scratch `.env` never
  existed, so P7's secret-read wording had no secret to leak even if it
  had reached a tool.
- Session resume/export reconciliation: not exercised live (all probes
  `--no-session`; no live session to interrupt/resume/export).

## Defects
| Severity | Reproduction | Expected | Actual | Session/run/event IDs | Sanitized evidence |
|---|---|---|---|---|---|
| Functional fail (blocks P2–P4, P6, P7 live proof) | any `--jsonl` probe whose lead issues a tool call or long-form answer on `llmgateway:gpt-5-nano` (P2/P3/P4/P6/P7) | `model.completed` with usage, then grounded answer | `model.failed` ~5.1 s after `model.started`, then `run.failed` with stderr `Execution failed: provider usage is uncertain; reservation remains held`; `provider_calls` row stays `started/ambiguous` so `_finalize_assignment_budget` raises `AccountingReconciliationRequired` | P2–P4/P6/P7 runs in scratch logs (7 events each: `run.started → diagnostic.workspace → budget.reserved → route.selected → model.started → model.failed → run.failed`) | stderr line above; direct-adapter repro shows the same call shape failing at the provider for `openai/`-prefixed ids (403) while canonical `gpt-5-nano` answers 200 with empty-usage streaming — P1's no-tool single-answer shape settles, tool-call shapes do not |
| Functional fail (blocks P5 live proof) | P5 on `llmgateway:gpt-4.1-mini` | multi-file rename delegated/executed | 2× `model.completed` then `tool.failed` on `execution_decision` and on `task`, terminal `run.failed: failure.consecutive_errors` | lead assignment `10798317-…`, 13 events, $0.044539 reserved | `tool.started/failed` pairs in `P5.stdout.txt`; stderr `Execution failed: failure.consecutive_errors` |
| Provider/account fault (root cause for the P2 signature) | raw `POST /v1/chat/completions` with `{"model":"openai/gpt-5-nano"}` + plan key | 200 or actionable 4xx naming the model | **403 `permission_denied`: "Direct provider routing is not available on coding plans. Use the canonical model id (e.g. `gpt-5-nano`) without a provider prefix and let the gateway handle routing."** | raw discovery script (zero charged calls for `GET /models`; the 403 probe is a failed call, no usage) | body quoted verbatim (no secret); canonical `gpt-5-nano` then returns 200 `"model":"openai/gpt-5-nano"` with exact `SKAIL_LIVE_OK` |
| Doc/config gap (retry-context item #2, confirmed fixed-shape) | plan §Setup `api_key_env = "DEVPASS_KEY"` | key from `.env` works as documented | checkout only recognises `LLMGATEWAY_API_KEY`/`DEVPASS_TOKEN`/`OPENAI_API_KEY`/`ANTHROPIC_API_KEY` (`handle_auth`, `_build_runtime_models` default); `LLMGATEWAY_API_KEY` mapping verified exit 0 | `auth check`/`auth status`/`config show` in gate log | `Credentials detected for: LLMGATEWAY_API_KEY`; `LLMGATEWAY_API_KEY: CONFIGURED` |
| Informational gap | `skail models list` with the retry user config loaded | llmgateway models visible (task instruction's verify step) | shows only built-in agent profiles + `fake:*` models; configured catalog entries are NOT listed (routing itself uses them — `route.selected` proves it) | gate log `MODELS_LIST exit=0` | `Configured Providers and Models: fake:fast-model …` (only) |
| Cost-authority gap (plan open Q4) | every live call this campaign | authoritative provider cost per streamed response | no usage/cost rows on any call (`in=0 out=0`, `actual=None`); ledger uses the larger of actual/estimate = conservative Skail envelope estimates | all `P*.stdout.txt` | `model.completed` payloads carry `delta: null` with no usage/cost fields |

## Verdict
- PASS / CONDITIONAL PASS / FAIL: **CONDITIONAL FAIL (transport +
  harness faults; no safety violation)** — the retry-context catalog gate
  is RESOLVED (auth via `LLMGATEWAY_API_KEY` verified, `[providers.llmgateway]`
  + trusted allowlist wired from the repo's own contract, P1 passes 4/4
  including exact `SKAIL_LIVE_OK` print-mode), spend is $0.0012
  (upper bound, far below $13.50/$15), no secret leaked, isolation held;
  but P2–P7 have no passing live evidence: P2–P4/P6/P7 hit the
  provider-side tool-call/usage settlement fault and P5 hits a
  harness-side `execution_decision`/`task` validation fault.
- Total live cost (larger of actual/estimate): **$0.001200 (estimate;
  provider reported $0.00 usage on all calls)**.
- Unresolved warnings: warm `--help` 0.874 s median (WARN band);
  TUI/perf matrix, approval/trust, resume/export, and fault-injection
  companions unmeasured live (covered only by offline suites); provider
  usage/cost never authoritative.

## Follow-ups
1. Fix streaming usage-settlement for llmgateway tool-call/long-form
   responses (missing `usage` leaves `provider_calls` ambiguous and every
   post-P1 probe fails closed with reservations held); add a minimal
   fake-provider regression test for `model.failed`-with-ambiguous-usage
   before changing code.
2. Fix `execution_decision`/`task` validation for the P5 rename shape
   (`failure.consecutive_errors` after two successful model calls);
   replay P5 from the retained sanitized event shape.
3. Decide whether `DEVPASS_KEY` should be an accepted `api_key_env`/auth
   alias or the plan updated to the `LLMGATEWAY_API_KEY` mapping (plan
   still names `DEVPASS_KEY`).
4. Show configured provider/catalog models in `skail models list` (or
   document that it only shows agent profiles + fake models), since the
   retry instructions used it as the catalog-gate check.
5. Pin canonical (prefix-less) gateway ids + the 2026-09-17 price table in
   a dated eval fixture; re-run only P2–P7 after fixes — the single
   full-suite retry allowance is now consumed, and any further campaign
   must preserve the aggregate <$15 ceiling.

## Teardown
- REQUIRED (not yet executed — logs below live in scratch until
  reviewed): close all probe terminals; verify no Skail child process or
  workspace lease remains; delete scratch `%TEMP%\skail-live-retry`
  (contains the only log copies with assignment/run ids) only after
  artifacts are reviewed; then from the main checkout:
  `git worktree remove C:\Users\plum\Documents\Works\skail-live-retry`
  and `git branch -D chore/live-retry-20260917` (report file lives at
  `evals/live-test-results-20260917-retry.md` on the main checkout, so no
  report is lost); clear `LLMGATEWAY_API_KEY` from the current process
  (it was only ever exported inside short-lived probe processes) and
  close the terminal. Do not modify the primary checkout beyond this
  report; never commit live journals, provider payloads, `.env`, scratch
  repos, or credentials. `legacy/skail/` untouched.
