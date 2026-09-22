# Live Test Results — 20260917-r3 / commit 6e9807f

> Isolation: `C:\Users\plum\Documents\Works\skail-live-r3` with the seven round-2 fix files applied and hash-verified before this campaign. Live agents saw only `%TEMP%\skail-live-r3\fixture`. No credential is recorded here.

## Environment
- Commit/worktree/fixture commit: `6e9807f` / isolated R3 worktree (removed at teardown) / `734afae`.
- Python / skail-harness / Windows / terminal: Python 3.14.6 / 0.1.0 / Windows 11 build 26200 / non-interactive PowerShell subprocess harness.
- CPU/RAM/power/network: AMD64 Family 26 Model 36; ASUS ROG Zephyrus G14 GA403GM; 31.1 GiB; power/network not captured.
- Candidate IDs: canonical `gpt-5-nano`, `gemini-2.5-flash-lite`, `gpt-4.1-nano`, `glm-5.3-flash`, `qwen-flash`, `gpt-4.1-mini`; six trusted USER entries dated 2026-09-17.
- Prices (input/output per 1M): $0.05/$0.40, $0.10/$0.40, $0.10/$0.40, $0.088/$0.25, $0.05/$0.40, $0.40/$1.60 respectively; no substitutions.
- Isolated user config: `%TEMP%\skail-live-r3\home\.skail\config.toml`; sanitized SHA-256 `95C3356E449014F4EE20C98C253F3BE49D285B1F1579FB3928B4B446C4B81215`. `HOME` and `USERPROFILE` both pointed there. The key was loaded in-process from main `.env`, length-checked as 48, passed only via environment, and all captured streams were redacted before disk writes.
- Auth gate: `auth check` exit 0 in 1.81s (`Credentials detected for: LLMGATEWAY_API_KEY`). `models list` exit 0 in 1.72s but again listed only built-in profiles and `fake:*` models; configured llmgateway models remain absent (informational gap).

## Budget ledger
| Probe | Calls | Est. cost | Provider actual | Reserved after | Cumulative upper bound |
|---|---:|---:|---:|---:|---:|
| P1 | 1 | $0.00 tracked | unknown | settled/released | $0.00 |
| P2 | 1 | $0.00 tracked | unknown | $0.010472 held | $0.00 |
| P3 | 1 | $0.00 tracked | unknown | $0.010477 held | $0.00 |
| P4 | 1 | $0.00 tracked | unknown | $0.010481 held | $0.00 |
| P5 | 3 | $0.00 tracked | unknown | $0.044611 held | $0.00 |
| P6 | 1 | $0.00 tracked | unknown | $0.010477 held | $0.00 |
| P7 | 1 | $0.00 tracked | unknown | $0.010481 held | $0.00 |
| **Campaign total** | **9 model turns** | **$0.00 tracked** | **$0.00 reported/unknown actual** | — | **$0.00 + prior ~$0.0012, far below $13.50 kill-switch and $15 cap** |

No probe was retried. P2/P3 established two consecutive identical usage-fault signatures; P4 was executed once as required and the campaign moved on without loops.

## Probe result
| ID | Mode | Route/assignment IDs | Attempts/peak children | TTFT/E2E | Outcome | Checks | Evidence path |
|---|---|---|---:|---|---|---|---|
| P1 | JSONL, no session | assignment `7d233ae2…`, run `a39db079…` | 1 lead call(s) / 0 children | 4.92s turn / 13.56s | PASS | run.completed; 0 tools/children | scratch `p1.stdout.txt` (removed) |
| P2 | JSONL, no session | assignment `9e555df4…`, run `07e20f50…` | 1 lead call(s) / 0 children | 5.17s turn / 12.78s | STILL FAILING — usage fault | model.failed; provider usage uncertain; reservation held | scratch `p2.stdout.txt` (removed) |
| P3 | JSONL, no session | assignment `2f889c2a…`, run `8046c04e…` | 1 lead call(s) / 0 children | 5.16s turn / 13.08s | STILL FAILING — usage fault | model.failed; provider usage uncertain; reservation held | scratch `p3.stdout.txt` (removed) |
| P4 | JSONL, no session | assignment `9a0b6f20…`, run `b7b6cb9e…` | 1 lead call(s) / 0 children | 5.18s turn / 13.17s | STILL FAILING — usage fault | model.failed; provider usage uncertain; reservation held | scratch `p4.stdout.txt` (removed) |
| P5 | JSONL, no session | assignment `0766cbd1…`, run `ad8ef25e…` | 3 lead call(s) / 0 children | 2.82s turn / 15.77s | STILL FAILING — validation fault | execution_decision failed ×2; grep failed ×2; failure.repeated_error | scratch `p5.stdout.txt` (removed) |
| P6 | JSONL, no session | assignment `6392a472…`, run `91f6fb52…` | 1 lead call(s) / 0 children | 5.17s turn / 13.42s | STILL FAILING — usage fault | model.failed; provider usage uncertain; reservation held | scratch `p6.stdout.txt` (removed) |
| P7 | JSONL, no session | assignment `3648946e…`, run `70d85460…` | 1 lead call(s) / 0 children | 5.18s turn / 13.14s | STILL FAILING — usage fault | model.failed; provider usage uncertain; reservation held | scratch `p7.stdout.txt` (removed) |
| TUI smoke | closed stdin | — | — | — / 1.83s | PASS | exit 1, clean `interactive mode requires a TTY`, no traceback/hang | scratch `tui-smoke.stderr.txt` (removed) |

### Round-2 fix resolution
- **P1: PASS (unchanged).** Canonical route and one model turn completed.
- **P2/P3/P4/P6/P7: STILL FAILING.** The round-2 `_complete_call` change did not resolve the observed live path. Each turn still emitted `model.failed` and terminated with `provider usage is uncertain; reservation remains held`. No tool or child event occurred.
- **P5: STILL FAILING.** Argument normalization/guidance changes did not resolve the live model output. Three model turns completed, but `execution_decision` failed twice and two concurrent `grep` calls failed, followed by `failure.repeated_error`. Validation failures still contributed to terminal repeated-error behavior in this path.

## Performance
| Metric | Samples | Median | p95/max | Threshold | Result |
|---|---:|---:|---:|---:|---|
| Warm `skail --help` R3 | 3 | 1.83s | 1.88s max | pass ≤0.75 / warn ≤1.25 | FAIL |
| Cold `skail --help` R3 | 1 | 1.79s | 1.79s | pass ≤1.50 / warn ≤2.50 | WARN |
| Cross-run warm startup | R1 / R2 / R3 | ~1.0s / 1.47s / 1.83s | R3 max 1.88s | investigate >20% | R3 FAIL; ~24% slower than R2 and ~83% slower than R1 |
| TUI closed-stdin | 1 | 1.83s | 1.83s | bounded smoke | PASS |
| P1 model turn / E2E | 1 | 4.92s / 13.56s | same | TTFT proxy ≤10 / E2E ≤30 | PASS |
| P2–P7 E2E | 1 each | 12.78–15.77s | 15.77s max | 60/180/300s bounds | PASS for timeout bounds; functional outcomes fail |

TTFT is proxied by `model.started` to first `model.completed`/`model.failed`; JSONL exposes no first-token delta.

## Safety/invariant evidence
- Assignment stickiness: one lead assignment per probe; P5 retained assignment `0766cbd1…` over three model turns.
- Maximum child attempts / peak concurrency: zero children on all probes; no violation, but positive fan-out remains unproven.
- Writer/worktree isolation: P5 selected worktree mode and created snapshot `e11f7196…`. Fixture status after campaign contained only untracked `.skail/`; source/test baseline was unchanged. `escaped.txt` absent and fixture `.env` absent.
- Approval/trust: not reached live; P6 failed before a question/approval event.
- Secret/canary scan: key **NOT FOUND** in sanitized logs/report; no canary was seeded; no fixture `.env` existed. Final report scan repeated before teardown.
- Session reconciliation: not exercised (`--no-session`).

## Defects
| Severity | Reproduction | Expected | Actual | Session/run/event IDs | Sanitized evidence |
|---|---|---|---|---|---|
| Functional — BUG1 live | P2/P3/P4/P6/P7 canonical nano tool-capable turn | Missing usage remains estimated and execution continues | `model.failed` then `run.failed`; reservation remains held | P2 run `07e20f50…`; same signature others | seven-event streams, exit 1 |
| Functional — BUG2 live | P5 canonical mini rename prompt | Decision and normalized grep arguments execute; validation errors do not terminate as consecutive errors | `execution_decision` failed ×2, `grep` failed ×2, then `failure.repeated_error` | run `ad8ef25e…` | 19-event stream, exit 1 |
| Performance | three warm help samples | median ≤1.25s at minimum WARN ceiling | median 1.83s | n/a | local timing harness |
| Informational | `models list` under isolated configured HOME | configured llmgateway catalog visible or scope documented | only `fake:*` models shown | n/a | auth/config/model gate logs |

## Verdict
- **FAIL (harness-side).** P1 transport/routing remains healthy, but both round-2 fixes are **STILL FAILING** on live paths; P2–P7 do not satisfy their objectives. No safety boundary violation was observed.
- Total live cost (larger of reported/estimate): **$0.00 tracked; actual provider cost unavailable**. Including prior campaign estimate (~$0.0012), well below $15.
- Unresolved warnings: missing usage/cost authority, configured-model listing gap, P7 boundaries and P6 approval blocked pre-tool, fan-out unexercised, and R3 warm startup regression.

## Follow-ups
1. Instrument `_complete_call` around adapter return versus exception to identify why live tool-call responses still enter `model.failed`; reproduce the precise streamed response shape offline.
2. Capture sanitized validation details for `execution_decision` and normalized `grep` arguments before another P5 change; current public events hide the rejected payload/reason.
3. Profile startup imports on the same machine: R3 median 1.83s regressed materially from both R1 and R2.
4. Make `models list` expose configured catalog entries or document its fake-only behavior.
5. Re-run only P2–P7 after targeted fixes; preserve isolation, redaction, and the <$15 aggregate cap.
