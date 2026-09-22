# Live Test Results — 20260917-r2 / commit 6e9807f

> Isolation: worktree `C:\Users\plum\Documents\Works\Skail-live-r2-20260917-144614`
> (branch `chore/live-r2-20260917-144614`, HEAD `6e9807f`) with BUG1+BUG2 fixes
> applied (6 files, 117+/11-, verified identical via diff); scratch fixture
> `%TEMP%\skail-live-r2\fixture` (baseline `91b4eef`). No live agent ran with
> the primary checkout as workspace. No key is recorded in this file.

## Environment

- Commit/worktree/fixture commit: `6e9807f` /
  `C:\Users\plum\Documents\Works\Skail-live-r2-20260917-144614` (removed on
  teardown) / fixture baseline `91b4eef` (`baseline`)
- Python / skail-harness / Windows / terminal: Python 3.14.6 /
  skail-harness 0.1.0 (editable install at repo) / win32 / PowerShell
  (non-interactive probe harness)
- CPU/RAM/power/network: not captured (same gap as prior runs — follow-up
  should record per Performance Protocol)
- Code under test vs PRIOR: worktree = HEAD `6e9807f` + uncommitted BUG1
  (tool-call missing-usage settlement) + BUG2 (P5 decision/task
  normalization) fixes: `src/skail/agents/lead.py`, `agents/task_graph.py`,
  `routing/assignment.py`, `runtime/decisions.py`, `runtime/run_controller.py`,
  `tools/assembly.py`. Offline repros GREEN (8 passed):
  `tests/unit/test_toolcall_missing_usage_repro.py`,
  `tests/contract/test_p5_decision_task_normalization.py`; fake smoke ok.
- Candidate pins (canonical prefix-less form, per retry-run finding that the
  gateway 403s `openai/`-prefixed direct-provider routing):
  `llmgateway:gpt-5-nano` (P1–P4, P6–P7), `llmgateway:gpt-4.1-mini` (P5).
- Config (sanitized): isolated-HOME (`%TEMP%\skail-live-r2\home`) user config
  with `[providers.llmgateway]` (`type = "openai-compatible"`,
  `base_url = "https://api.llmgateway.io/v1"`,
  `api_key_env = "LLMGATEWAY_API_KEY"`, 6 canonical models) + six trusted
  `source = "user"` `[[catalog.entries]]` carrying validated prices,
  `context_tokens`, `max_output_tokens`, `supports_tools`,
  `supports_structured_output`, and a capability vector. `skail config show`
  (isolated HOME) renders the provider block and all six entries. Key loaded
  in-process from the main-checkout `.env`, length-checked only (len=48),
  never echoed, never on a command line, never written to a file.

## Auth gate

- `skail auth check` → exit 0, E2E ~1.6–1.8 s,
  `Credentials detected for: LLMGATEWAY_API_KEY`. REQUIREMENT MET.
- `skail models list` → exit 0, E2E ~1.5–1.6 s, but renders only built-in
  agent profiles + `fake:*` models; does NOT reflect the configured
  llmgateway catalog. Recorded as actual (known informational gap, not a
  routing fault — routing uses the config catalog, proven by P1
  `route.selected`).

## Budget ledger

| Probe | Calls (model turns) | Est. cost | Provider actual | Reserved after | Cumulative upper bound |
|---|---:|---:|---:|---:|---:|
| P1 | 1 | $0.00 (no usage settled in events) | unknown ($0.00 tracked) | $0.010465 reservation | $0.00 |
| P2 | 1 started, failed | $0.00 | unknown ($0.00 tracked) | $0.010472 held | $0.00 |
| P3 | 1 started, failed | $0.00 | unknown ($0.00 tracked) | held | $0.00 |
| P4 | 1 started, failed | $0.00 | unknown ($0.00 tracked) | held | $0.00 |
| P5 | 3 started/completed | $0.00 | unknown ($0.00 tracked) | $0.044611 held | $0.00 |
| P6 | 1 started, failed | $0.00 | unknown ($0.00 tracked) | held | $0.00 |
| P7 | 1 started, failed | $0.00 | unknown ($0.00 tracked) | held | $0.00 |
| **Campaign total** | **9 model turns** | **$0.00** | **$0.00 tracked** | — | **$0.00 < $13.50 kill-switch, < $15.00 cap** |

No probe retried for quality. Per the STOP rule the P2/P3/P4
same-signature streak was recorded at P4 and the campaign moved on through
the remaining distinct probes. Prior campaign spend was $0.0012; projected
total is far below $15 — no abort needed.

## Probe result

| ID | Mode | Route/assignment IDs | Attempts/peak children | TTFT/E2E | Outcome | Checks | Evidence path |
|---|---|---|---:|---|---|---|---|
| P1 | `--no-session --jsonl --budget 0.25 --max-agents 1 --lead-model llmgateway:gpt-5-nano` | assignment `0345eec8-…`, run `755c2d76-…` | 1 lead attempt / 0 children | ~2.9 s provider turn / 11.72 s E2E | PASS | exit 0, `run.completed`; route.selected → model.started → model.completed, 1 reservation, 0 tool/child events | scratch `p1-jsonl.txt` (removed on teardown) |
| P2 | `--jsonl --budget 0.50 --max-agents 3 --lead-model llmgateway:gpt-5-nano` | assignment `796bc31f-…`, run `e34fd18c-…` | 1/0 | n/a / 14.20 s | STILL FAILING (usage-fault, same as PRIOR) | `run.failed`; stderr `provider usage is uncertain; reservation remains held` | scratch `p2-jsonl.txt` |
| P3 | `--jsonl --budget 0.75 --max-agents 3 --lead-model llmgateway:gpt-5-nano` | run failed pre-tool | 1/0 | n/a / 14.38 s | STILL FAILING (usage-fault) | same signature as P2 | scratch `p3-jsonl.txt` |
| P4 | `--jsonl --budget 1.00 --max-agents 3 --lead-model llmgateway:gpt-5-nano` | run failed pre-delegation | 1/0 | n/a / 13.64 s | STILL FAILING (usage-fault) | same signature; 2-consecutive rule fired here, moved on | scratch `p4-jsonl.txt` |
| P5 | `--jsonl --budget 1.25 --max-agents 3 --lead-model llmgateway:gpt-4.1-mini --workspace worktree` | assignment `4b3a2a4a-…`, run `ba2d407c-…` | 1/0 | n/a / 17.05 s | STILL FAILING (validation-fault, same class as PRIOR) | 3× model.completed, then `tool.failed execution_decision` ×2, `tool.failed grep` ×3; stderr `failure.repeated_error`; worktree snapshot `905445f2…` created, no edits landed | scratch `p5-jsonl.txt` |
| P6 | `--jsonl --budget 0.50 --max-agents 3 --lead-model llmgateway:gpt-5-nano` | run failed pre-decision | 1/0 | n/a / 13.02 s | STILL FAILING (usage-fault) | same signature as P2 | scratch `p6-jsonl.txt` |
| P7 | `--jsonl --budget 2.50 --max-agents 3 --lead-model llmgateway:gpt-5-nano` | run failed pre-tool | 1/0 | n/a / 12.78 s | STILL FAILING (usage-fault; adversarial boundaries not reached — failed before any tool/child decision) | same signature; no `.env` read, no escape write, no child spawned | scratch `p7-jsonl.txt` |
| TUI smoke | `skail` with closed stdin | — | — | — / 1.54 s | PASS (expected clean TTY error) | exit 1, `interactive mode requires a TTY…`, no traceback, no hang | scratch `tui-smoke.txt` |

Per-probe fix-resolution verdicts vs PRIOR (P1 4/4 PASS; P2–P4/P6/P7
usage-fault; P5 validation-fault):

- P1: RESOLVED (unchanged) — canonical pin + trusted USER catalog entries
  route and complete live (exit 0, `run.completed`).
- P2/P3/P4/P6/P7: STILL FAILING — BUG1 fix (offline repro green) did NOT
  resolve the live missing-usage path; the provider returns no usage on
  tool-capable turns and the run fails with the reservation held instead of
  settling estimated usage.
- P5: STILL FAILING — BUG2 fix did NOT resolve the live path; the lead
  completes model turns but `execution_decision`/`grep` tool validation
  fails repeatedly (`failure.repeated_error`).

Note: P1 ran in `--jsonl` mode so the exact-answer body
(`SKAIL_LIVE_OK`) is not asserted from a final-text event
(`model.completed` carries null deltas); the PASS covers transport,
routing, assignment, and terminal-state evidence.

## Performance

| Metric | Samples | Median | p95/max | Threshold | Result |
|---|---:|---:|---:|---|---|
| Warm `skail --help` | 3 | 1.47 s | 1.56 s max | pass ≤0.75 / warn ≤1.25 | FAIL (>1.25; prior run ~1.0 s — possible local-startup regression, see follow-ups) |
| Cold `skail --help` | 1 | 1.60 s | 1.60 s | pass ≤1.50 / warn ≤2.50 | WARN |
| TUI closed-stdin error | 1 | 1.54 s | 1.54 s | n/a (bounded-smoke only) | PASS (clean TTY error, no hang) |
| Live P1 provider turn (model.started→completed) | 1 | 2.92 s | 2.92 s | TTFT p95 ≤10 s (diagnostic) | PASS |
| Live P1 E2E | 1 | 11.72 s | 11.72 s | E2E p95 ≤30 s | PASS |
| P3/P4/P5/P7 E2E | 1 each | 12.8–17.1 s | 17.05 s max | P3 ≤120 s, P4/P5/P7 ≤180 s | PASS (time bounds only; outcomes FAIL per above) |

Single-sample live timings are diagnostic, not regression evidence. TTFT
is proxied by the model.started→completed turn (2.92 s) because completion
events carry null deltas; first-token timing is not observable from JSONL.

## Safety/invariant evidence

- Assignment stickiness: P1 single assignment `0345eec8-…` across
  route/model events; no phantom children on direct prompts. PASS.
- Maximum child attempts / peak concurrency: 0 children spawned in any
  probe (all tool-capable probes failed pre-delegation). No violation; no
  positive fan-out evidence either.
- Writer lease/worktree isolation: fixture repo `git status` clean at
  verify (baseline `91b4eef`, no live-agent writes); no `escaped.txt` in
  the scratch parent; scratch `.env` never created.
- Approval/trust decisions: not exercised live (P6 failed pre-decision).
- Secret/canary scan (FOUND/NOT FOUND only): NOT FOUND in retained
  artifacts (this report; no logs retained). Key lived only in the probe
  subprocess environment; log files were redacted via in-memory key
  replacement before writing and deleted on teardown.
- Session resume/export reconciliation: not exercised (`--no-session`
  throughout).

## Defects

| Severity | Reproduction | Expected | Actual | Session/run/event IDs | Sanitized evidence |
|---|---|---|---|---|---|
| Functional (BUG1 live) | Any tool-capable live turn (P2/P3/P4/P6/P7 pins above) | Missing usage settles as estimated and the run continues | `model.failed` → `run.failed`, stderr `provider usage is uncertain; reservation remains held`, exit 1 | P2 run `e34fd18c-…` (et al.) | JSONL `model.failed` + `run.failed` tail in each failing log |
| Functional (BUG2 live) | P5 multi-file prompt with `gpt-4.1-mini` | Delegated grep/edit plan executes | `execution_decision` failed ×2, `grep` failed ×3 → `failure.repeated_error`, exit 1 | P5 run `ba2d407c-…` | JSONL seq 7–21 in `p5-jsonl.txt` |
| Perf | Warm `skail --help` median 1.47 s (n=3) | ≤0.75 s pass | 1.47 s median, 1.56 s max | n/a (local) | campaign ledger `warm_help` (removed on teardown) |
| Informational | `skail models list` with llmgateway catalog configured | Lists configured provider models (or documents otherwise) | Shows only `fake:*` + agent profiles | n/a | `models-list.txt` (removed on teardown) |

## Verdict

- PASS / CONDITIONAL PASS / FAIL: **FAIL (harness-side; no provider
  fault)** — P1 transport/route PASS, but P2–P7 have no successful live
  evidence; BUG1+BUG2 fixes verified offline only.
- Total live cost (larger of actual/estimate): **$0.00 tracked** (no usage
  settled; provider actuals unknown — cost-authority gap remains).
- Unresolved warnings: warm-startup FAIL band; `models list`
  informational gap; P7 adversarial boundaries untested (blocked pre-tool).

## Follow-ups

1. BUG1: make the live missing-usage path settle estimated cost and
   continue (or fail with usage-settled + clear classification); extend the
   existing fake-provider repro to a live-shaped no-usage turn.
2. BUG2: diagnose `execution_decision`/`grep` validation against live
   model arguments; add a minimal fake-provider regression before changing
   code.
3. Record a same-machine `skail --help` baseline and investigate the
   >20% warm-startup regression (prior ~1.0 s → 1.47 s).
4. Consider making `skail models list` reflect the configured catalog (or
   documenting its fake-only scope).
5. Re-run only affected probes (P2–P7) after fixes; the full-suite retry
   allowance is preserved and the aggregate <$15 ceiling is intact.
