# Live diagnostics 2026-09-17 — P2 + P5 (sanitized metadata only)

Diagnostics-only. No behavior fixes were made. No raw logs, journals, payloads,
prompts-beyond-quoted-strings, or secrets are copied into this repo; all
evidence below is sanitized metadata. Raw evidence formerly in TEMP
`C:\Users\plum\AppData\Local\Temp\skail-diag-20260917-184716` was deleted at
the completed teardown (see §10); the sanitized metadata below is the
retained record.

## 1. Scope and tree state

- Main HEAD `6e9807f` (`fix(tui): phase 5 close-out…`) plus the original dirty
  seven-file patch, preserved with **no behavior fixes**. Modified src files
  (7): `agents/lead.py`, `agents/task_graph.py`, `routing/assignment.py`,
  `runtime/decisions.py`, `runtime/model_middleware.py`,
  `runtime/run_controller.py`, `tools/assembly.py` (+416/−18 lines total).
- Pre-run preservation: `main-tracked.diff` (25557 bytes),
  `tracked_diff_sha256 =
  d3c86c5e8acbaf35abd87a1430bb0a34361c16ec0a041fe289f0444cfd81767f`
  (saved patch SHA identical). `main_has_live_diag: false` — no `_live_diag`
  instrumentation exists in main. (The `.env` hash recorded in the manifest is
  deliberately NOT published here.)
- Worktree-only extras (NOT part of the preserved main patch, instrumentation
  only): untracked `src/skail/_live_diag.py`, and `runtime/failure_monitor.py`
  modified in the isolated worktree
  (`C:\Users\plum\Documents\Works\Skail-live-diag-20260917-184716`) while
  absent from the main seven-file diff. Worktree diag caller line numbers
  therefore differ from main source lines — the two are labeled separately
  throughout this report.
- Fixture (isolated TEMP copy, observed file list): `README.md`,
  `calculator.py`, `api/__init__.py`, `api/users.py`, `core/__init__.py`,
  `core/names.py`, `tests/__init__.py`, `tests/test_names.py`,
  `.skail/{approvals,questions}.sqlite`. Fixture repo commit
  `86eac64615c8dd3d757382b4289f4f608077cbce` (`fixture baseline`), separate
  from main history as expected; the file list above is the actual fixture
  used.

## 2. Environment and invocation

- Env: Python `3.14.6` (`…\pythoncore-3.14-64\python.exe`), Windows
  `Windows-11-10.0.26200-SP0`, skail `0.1.0`.
- Invocation: `sys.executable -m skail …` with `PYTHONPATH=<worktree>/src`
  (verified in harness env setup). The `skail` console launcher is NOT on PATH
  (`shutil.which` → None), so all startup figures are **module-equivalent**
  (`python -m skail --help`), not literal console-launcher measurements.
- Isolation: `HOME`/`USERPROFILE` (and for live runs also
  `APPDATA`/`LOCALAPPDATA`, `XDG_*`) redirected to TEMP `home/`; offline steps
  ran with provider keys stripped (`API_KEY`/`APIKEY`/`SECRET`/`TOKEN`/
  `PASSWORD`/`CREDENTIALS` patterns); live children got a minimal env (PATH,
  SystemRoot, WINDIR, COMSPEC, PATHEXT, TEMP, TMP) + `SKAIL_DISABLE_TELEMETRY=1`
  + the single live key only. Zero live calls during preflight/startup.

## 3. Config reconstruction (secret-free; exact R3 TOML unavailable)

The exact R3 TOML is NOT reproduced here (and its isolated copy is deleted).
Fidelity limitation: what survives in sanitized form is the effective summary —
manual routing + explicit per-probe `--lead-model` pins (R3 tool-capable
intent) — so any reconstruction below is approximate, not a byte-faithful R3.
Prices/flags below are **operator-supplied test metadata**, not measured
performance. No supported `max_model_calls` config exists (streaming cancel
enforced caps instead; `FailureMonitor.max_calls` is never wired to CLI).

Six trusted user-catalog entries (all `trusted: true`, `tools: true`):

| model | in $/M | out $/M |
|---|---|---|
| gpt-5-nano | 0.05 | 0.4 |
| gemini-2.5-flash-lite | 0.10 | 0.4 |
| gpt-4.1-nano | 0.10 | 0.4 |
| glm-5.3-flash | 0.088 | 0.25 |
| qwen-flash | 0.05 | 0.4 |
| gpt-4.1-mini | 0.4 | 1.6 |

Reproduction template (secret-free; `<KEY>` never stored):

```toml
[routing]
mode = "manual"
lead_model = "llmgateway:<probe-pin>"   # P2: gpt-5-nano; P5: gpt-4.1-mini

[[catalog.entries]]
model = "<name>"; trusted = true
[catalog.entries.fields]
input_usd_per_million = <n>; output_usd_per_million = <n>
supports_tools = true
# Any further operator fields (dates, context windows, max tokens,
# capabilities) were NOT captured in the sanitized summary and must be
# re-supplied by the next operator from their own config.
```

## 4. Probes: prompts, flags, budgets, counts

Prompts/flags each defined once in the harness and recorded in the
once-written launch markers (`p2.launched`/`p5.launched`, written before spawn;
re-runs skip if the marker exists):

- P2 prompt: "Read README.md and explain in three bullets what this fixture
  does. Do this yourself; do not delegate or modify files." Flags: `--jsonl
  --no-session --budget 0.50 --max-agents 3 --lead-model llmgateway:gpt-5-nano`.
- P5 prompt: "Rename the fixture function `normalize_name` to
  `canonicalize_name` across `core/names.py`, `api/users.py`, and tests.
  Preserve the public alias, update tests, use isolated worker worktrees for
  independent edits/review, and run the focused suite." Flags: `--jsonl
  --no-session --budget 1.25 --max-agents 3 --workspace=worktree --lead-model
  llmgateway:gpt-4.1-mini`.
- Budgets: hard CLI caps P2 ≤ $0.50, P5 ≤ $1.25. Prior aggregate ~$0.0012
  (operator-supplied) + worst-case caps $1.75 = **$1.7512 < $15** gate.
- Streaming call caps (online enforcement, accepted race: a `model.started`
  for N+1 may already be in flight when the Nth `completed` arrives; post-hoc
  counts recorded): P2 cap 2, P5 cap 8. Neither cap tripped
  (`cancelled_at_cap: false`, `cancel: null`, `cap_overrun: false` both).
  Actual `model.started` counts: **P2 = 1, P5 = 3** — within bounds.
- UTC event spans (`occurred_at`, first→last; event timestamps only, no
  wall-clock/process-time measurement claimed, no invented elapsed figures):
  P2 `2026-09-17T23:37:56.494821Z` → `2026-09-17T23:38:01.890138Z`;
  P5 `2026-09-17T23:38:06.519736Z` → `2026-09-17T23:38:14.596083Z`.
  (Startup summary clock `19:23:45` is local time ≈ 23:23 UTC — consistent;
  this resolves the local-vs-UTC timestamp conflict in prior summaries.)
- stdout event types. P2 (7 events, terminal `run.failed`): `run.started`,
  `diagnostic.workspace` (shared mode), `budget.reserved`, `route.selected`,
  `model.started` ×1 (gpt-5-nano), `model.failed` ×1, `run.failed`. No tool
  events. Sanitized stderr (exact, whole file): `Execution failed: provider
  usage is uncertain; reservation remains held`.
- P5 (21 events, terminal `run.failed`): `model.started` ×3 /
  `model.completed` ×3 (gpt-4.1-mini); `tool.started` execution_decision ×2,
  grep ×3; `tool.failed` execution_decision ×2, grep ×3. No
  `tool.validation_rejected` events anywhere. Sanitized stderr (exact, whole
  file): `Execution failed: failure.repeated_error`.
- Retry behavior: two repeated identical errors produce the terminal signal
  with **no probe retries** (no 4th model call in P5). The P5 third grep is the
  same already-generated parallel fan-out from one model response (three
  `tool.started` grep events sequenced 15→16→17, then three `tool.failed`
  18→19→20), NOT another probe retry. Ordered emission must not be read as
  absence of concurrency (DeepAgents parallel fan-out).

## 5. P2 root finding: handler-raised read timeout masked at finalization

- Exact failure (worktree diag, 1 record in `p2.diag.jsonl`):
  `error_class = httpx.ReadTimeout`, `cause = httpcore.ReadTimeout`,
  `phase = handler-raised`, `response_available = false`; `_complete_call` was
  never reached. Representative metadata (call ID omitted as unnecessary):
  `{"site": "middleware.handler_exception", "mode": "async",
  "error_class": "httpx.ReadTimeout", "cause": {"cause":
  "httpcore.ReadTimeout", "context": null}, "phase": "handler-raised",
  "response_available": false}` + 8 truncated trace frames
  (`model_middleware → factory.inner_handler → run_helpers.async_wrapper →
  prompt_caching → factory._execute_model_async → chat_models.ainvoke →
  agenerate_prompt → agenerate`). The truncated 8-frame list is metadata only
  and does not identify a socket primitive — no such claim is made.
- Preserved main branch (distinct from worktree diag coordinates
  `model_middleware.py:147` frame / `:149` diag site):
  `src/skail/runtime/model_middleware.py:94` (`response = await
  handler(bound)`), `:95–100` (mark ambiguous, rethrow as
  `AccountingReconciliationRequired`). Finalization:
  `src/skail/runtime/run_controller.py:393–395` raises the generic
  `AccountingReconciliationRequired("provider usage is uncertain; reservation
  remains held")` when an `ambiguous` call row exists — this masks the
  original timeout. The sanitized stderr above confirms the exact generic
  message reached the terminal.
- NOT proven: gateway bug, account issue, or missing-usage causation; no
  configured-timeout attribution is made without source proof.

## 6. P5 root finding: decision-plan shape rejection, then decision gate
(NOT a grep arg-normalization bug)

- Both `execution_decision` attempts carried exactly the arg keys
  `constraints, mode, objective, plan, reason` (key names only, no values
  recorded). The embedded `plan` was rejected at schema parse:
  `missing: schema_version, policy_version, revision, nodes`;
  `extra_forbidden: name, steps`. Error detail codes `missing` /
  `extra_forbidden`; admission codes first `decision.plan_invalid`, then
  `decision.repair_exhausted` (repair budget consumed by the first failure).
- Preserved main sources: `src/skail/runtime/decisions.py:119–134` (`_parse` →
  `DecisionAdmissionError("decision.plan_invalid")`), `:157–160`
  (`_consume_repair` → `"decision.repair_exhausted"`); schema
  `src/skail/domain/plans.py:59–65` (`ExecutionPlan` requires
  `schema_version, policy_version, revision, nodes`, `extra="forbid"`).
- The three greps (arg keys exactly `path, pattern`) were gated BEFORE any
  grep schema/tool execution: `execution.decision_required` via
  `ExecutionDecisionGate.prepare_response` in main
  `src/skail/runtime/decisions.py:85–86` (`if not self.allows(…): _reject(…,
  "execution.decision_required")`). Correction to prior summaries: **no
  `prepare_response.py` file exists in main** — the method lives in
  `decisions.py` (worktree diag caller `decisions.py prepare_response :104`
  / `:111` confirms).
- Repeated-error signal path (main lines): `src/skail/tools/assembly.py:489–491`
  (`observe_error` → raise `RuntimeError(signal)`) +
  `src/skail/runtime/failure_monitor.py:49–50` (`_error_counts[value] >= 2` →
  `"failure.repeated_error"`). Full P5 diag sequence (27 records — this
  resolves the 27-vs-26 conflict; P2 has exactly 1 record, 28 total):
  handler_success → schema_rejected → rejected(`plan_invalid`) →
  prepare_rejected → tool_rejected → monitor.error(null) →
  error_observed(`plan_invalid`) → handler_success → schema_rejected →
  rejected(`repair_exhausted`) → prepare_rejected → tool_rejected →
  monitor.error(null) → error_observed(`repair_exhausted`) → handler_success →
  3× tool_gated(grep) → 3× tool_rejected(grep) → monitor.error(null) +
  error_observed → 2× [monitor.error(`failure.repeated_error`) +
  error_observed(`failure.repeated_error`)].

## 7. Costs (honest accounting)

- Initial reservations ONLY: P2 `$0.010472`, P5 `$0.044611`
  (`budget.reserved` events). Zero `in/out_tokens` usage events and no
  settlement deltas were observed, so the **actual bill is unknown**.
- P2's `reservation remains held` state is evidenced by its stderr; P5's
  `$0.044611` must NOT be described as held/paid — it is an initial reserve
  only. No `$0 charged` claim is made, and no extra calls were issued to query
  billing.

## 8. Startup profile (offline, source-mapped)

Warm wall (`-m skail --help`, n=7): median **1.0271s** (min 0.9865, max
1.0946; samples 1.0686, 1.0946, 1.0271, 1.0006, 0.9985, 0.9865, 1.0493).
Import-entry control (`-c import skail.cli.main`, n=7): median **1.0052s**
(min 0.9754, max 1.0196). `python -c pass` (n=7): median **0.0269s** (min
0.0262, max 0.036). Paired HEAD-vs-dirty (n=7 each): current median 0.9792s
vs HEAD-baseline 1.0026s, delta **−0.0234s**; importtime `sum(self)` 0.815s
vs 0.832s (889 modules both). Observed startup ≈ 1s; eager framework imports
are the dominant current floor; R1→R3 historical growth is UNPROVEN as a code
effect (no load/cache/env data for those runs) and the dirty patch is not the
cause (most dirty files are not even on the `--help` import path).

Importtime (current; cumulative overlaps — parents include children, NEVER
summed). Top self: `langsmith.schemas` 51.1/54.3ms,
`charset_normalizer.api` 40.4/45.0ms, `skail.domain.security` 18.5/83.2ms,
`langchain_core…chat_models` 11.8/**279.9ms**. Top cumulative:
`skail.cli.main` 738.0ms, `skail.cli.commands` **384.8ms**,
`skail.providers.base` 284.9ms, `chat_models` 279.9ms, `skail.sessions`
260.3ms, `skail.sessions.checkpoints` **235.7ms**. Verified first-hop
importers: `providers/base.py:6`
(`from langchain_core…chat_models import BaseChatModel`) →
`chat_models` cum 279.9ms; `sessions/checkpoints.py:15–17` (langgraph
checkpoint imports) cum 235.7ms, re-exported via `sessions/__init__.py:3`,
pulled in via `cli/commands.py:20–22` (cum 384.8ms).

## 9. Verification (offline preflight + secrecy)

- Preflight: 8/8 steps passed — worktree imports, config load, fake-provider
  smoke, targeted ruff on diag modules, compileall on diag modules,
  logger canary (redaction/gating), **16 existing tests passed**
  (`test_failure_monitor`, `test_context_assembly`,
  `test_execution_decisions`), synthetic streaming-cancel (cancel at cap
  works). Independent heavy-readiness check: PASS (as handed down; no
  contradicting evidence in TEMP).
- Secrecy: all six retained logs (`p2/p5` × stdout/stderr/diag) scanned
  byte-wise UTF-8 + UTF-16LE for the live key and the canary — all
  NOT_FOUND (12/12). Key material was printed as length (`48`) only, never
  stored. Raw logs were already redacted by the harness scrubber.
- Patch preservation: §1 hashes; `main_has_live_diag: false`; only this
  report file is added to main.

## 10. Teardown checklist — COMPLETED 2026-09-18 (UTC)

- [x] Report corrections applied: fixture commit corrected to full
  `86eac64615c8dd3d757382b4289f4f608077cbce` (`fixture baseline`, fixture
  repo, separate from main history as expected); TOML typo fixed to
  `[catalog.entries.fields]`.
- [x] Preservation verified BEFORE teardown (in-memory manifest): all 17
  tracked/untracked original files byte-identical to pre-run manifest
  hashes; main `.env` hash unchanged (comparison only, never printed);
  current binary `git diff` SHA256 =
  `d3c86c5e8acbaf35abd87a1430bb0a34361c16ec0a041fe289f0444cfd81767f`,
  matching the saved `.patch` SHA. No unexpected changes; no restore of
  unfamiliar work needed.
- [x] Final leak scan BEFORE deletion: report + all 12 run artifacts
  (`p2/p5` stdout/stderr/diag, run-summaries, effective-config,
  preflight-report, pre-run-manifest, startup summary/timings) scanned
  UTF-8 + UTF-16LE against the live key (read from `.env` in-process,
  never printed) — all NOT_FOUND. `git grep _live_diag -- src` in main:
  no match; no `src/skail/_live_diag.py` in main. Process inventory
  (`Win32_Process` python.exe): no command lines referencing the owned
  TEMP root or worktree; historic PIDs 25512/3932 absent; nothing killed.
- [x] Worktree logging removed BEFORE worktree deletion: 4 diagnostic-edited
  tracked files (`model_middleware.py`, `decisions.py`, `assembly.py`,
  `failure_monitor.py`) restored to original main bytes (manifest-hash
  match for the first three; `failure_monitor.py` restored to HEAD-clean
  via `git checkout`, CRLF-normalized identical); `_live_diag.py` deleted
  plus `__pycache__` cleanup. Post-removal `git grep
  _live_diag|SKAIL_DIAG_LOG|SKAIL_LIVE_DIAGNOSTICS -- src` in worktree: no
  match. Worktree binary `git diff` SHA256 equals the original patch SHA
  above (7 files, +416/−18); `graphify update .` run in the worktree (AST
  re-extract OK). Main code diff untouched throughout.
- [x] Owned scratch removed ONLY (exact paths, no wildcards, `--force`
  authorized for the intentionally-dirty diagnostic copy; no
  `reset/clean/stash` on main): `rtk git worktree remove --force
  C:\Users\plum\Documents\Works\Skail-live-diag-20260917-184716`;
  `rtk git branch -D chore/live-diag-20260917-184716`; deleted owned TEMP
  root `C:\Users\plum\AppData\Local\Temp\skail-diag-20260917-184716`
  (stdout/stderr/diag, `run_diagnostics.py`, startup profile incl. HEAD
  archive, `results/`, isolated `home/`, `fixture/`) and owned siblings
  `skail-diag-20260917-184716.patch`, `skail-diag-setup.ps1`,
  `skail-diag-env.ps1`, `skail-diag-paths.json`, `skail-diag-env.json`,
  `skail-diag-verify.ps1` (its extra paths `skail-diag-check.py` absent /
  `skail-diag.log` deleted). Untouched: all `skail-phase22/24` worktrees,
  other branches, preexisting `skail-live` folder, main `.skail/`,
  `package.json`, and user untracked repros/reports.
- [x] Post-teardown verification: `git worktree list` shows no
  `live-diag-20260917` entry (phase22/24 entries intact); branch
  `chore/live-diag-20260917-184716` absent; worktree, TEMP root, patch,
  helper scripts, and `skail-diag.log` paths all absent
  (`Test-Path … False`); no `_live_diag` source/strings in main; main
  binary diff SHA still the original value; original untracked
  repros/reports preserved. `graphify update .` run in main after report
  creation (AST re-extract OK, no paid calls); rerun after this final
  §10 edit if the grader requires a fresh index.
- This report remains the only new authored deliverable in main (no
  commit). Source citations in §§5–6 remain the main-repo paths.
