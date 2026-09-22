# Live Test Results — 2026-09-17 R4

**Run ID:** live-20260917-r4
**Date (UTC):** 2026-09-17
**Branch:** `skail-tui-rework` @ `eb77468`
**Report file:** `evals/live-test-results-20260917-r4.md`
**Mode:** live probes via owned TEMP harness rerun — NO live calls made during report writing; NO code changes.
**Teardown:** COMPLETED 2026-09-18 UTC (see §8 checklist; scans clean, owned worktree/branch/fixture/home/harness removed).

---

## 1. Environment

| Field | Value |
|---|---|
| OS | Windows 11 |
| Python | 3.14.6 |
| Repo | `C:\Users\plum\Documents\Works\Skail`, branch `skail-tui-rework` @ `eb77468` |
| Worktree | `Skail-live-20260917-210415` @ `eb77468`, branch `chore/live-probe-20260917-210415` |
| Fixture baseline | `bffc15f4` |
| Isolated HOME | `%TEMP%\skail-live\home-20260917-210415` |
| Credential assumption | Plan `DEVPASS_KEY` assumption stale — checkout uses `LLMGATEWAY_API_KEY` (length 48, env-only) |
| Secret scans | NOT FOUND on all probes (no leak) |
| Warm-start reference | `skail --help` still > threshold per prior runs; cite live-diagnostics 1.027 s module-equivalent (not re-measured in R4) |

Model pins (all canonical, prefix-less):

| Probes | Lead model |
|---|---|
| P1, P6, P7 | `llmgateway:gpt-5-nano` |
| P2, P3, P4 | `llmgateway:gemini-2.5-flash-lite` |
| P5 | `llmgateway:gpt-4.1-mini` |

Rerun argv (verified, used for all P1–P7 reruns):

```text
python -m skail --jsonl --no-session --max-agents 3 --budget <cap> --lead-model llmgateway:<id> [--workspace worktree --delegation auto for P4/P5/P7] <positional prompt>
```

Notes:

- Positional prompt form only (no `-p` flag) — required after attempt0 finding.
- `--workspace worktree --delegation auto` applied for P4/P5/P7 only.
- No prompts reproduced beyond plan strings (already public in plan). No key material. No raw payloads.

---

## 2. Budget ledger

- Sum of per-probe caps: **$6.75**; kill-switch **$13.50** not reached.
- `budget.reserved` strings per probe (reservation, NOT spend):

| Probe | budget.reserved |
|---|---|
| P1 | 0.010465 |
| P2 | 0.011114 |
| P3 | 0.011123 |
| P4 | 0.011131 |
| P5 | 0.044611 |
| P6 | 0.010477 |
| P7 | 0.010481 |
| **Total reserved** | **≈ $0.1094** |

- No `usage` / token keys in any JSONL; all `model.completed` events carry `delta: null`.
- Actual billed spend **UNKNOWN** — never claim $0 charged, and never present any reservation figure as spend.
- First attempt (attempt0): all 7 probes `rc=2` `EXIT_USAGE`, **$0 spend**; logs preserved as attempt0.

---

## 3. Probe results

### Attempt0 (superseded, retained for record)

- All 7 probes exited `rc=2` (`EXIT_USAGE`) due to staged-harness argv bug (`-p` + `--jsonl` mutual exclusion).
- $0 spend. Logs preserved as attempt0. Fixed in owned TEMP harness only (no repo code change).

### Rerun outcomes (authoritative)

| Probe | Exit | Envelope | Detail (verified) |
|---|---|---|---|
| P1 | 0 | `run.completed` | 1/1, `nano` path; pass |
| P2 | 0 | `run.completed` | 2/2, `flash-lite` path; `execution_decision` + `read_file` ok; pass |
| P3 | 1 | `run.failed` / `failure.repeated_error` | 3/3; `edit_file` × 2 failed; fail |
| P4 | 0 | `run.completed` | 1/1; no tools; pass |
| P5 | 1 | `run.failed` / `failure.repeated_error` | 4/4; `execution_decision` × 2 + `task` + `ls` failed; fail |
| P6 | 1 | `run.failed` | `provider usage is uncertain; reservation remains held`; 1 started / 0 completed; fail |
| P7 | 1 | `run.failed` | Same shape as P6 (`provider usage is uncertain; reservation remains held`); fail |

Cross-probe invariants (all reruns):

- Zero children spawned on all probes.
- Single assignment ID per probe (stable).
- TTFT ~0.2–0.4 s; E2E 1.6–8.2 s.
- Failure codes live only in stderr text; stdout `run.failed` envelope carries family/status only.

---

## 4. Performance

- TTFT ~0.2–0.4 s per probe; E2E 1.6–8.2 s (rerun set).
- Warm `skail --help` still above threshold per prior runs — cited from live-diagnostics 1.027 s module-equivalent; **not re-measured** in R4 (no re-probe per task constraints).

---

## 5. Safety / invariant evidence

- No secret leak: env-only credential handling; scans NOT FOUND on all probes.
- No workspace escape: worktree-confined execution (`--workspace worktree` where applicable); no escape observed.
- No orphan processes: zero children spawned on all probes.
- Single-assignment stability: one assignment ID per probe, stable throughout.
- Kill-switch untouched: sum caps $6.75 vs $13.50 kill threshold — never reached.
- Billing honesty: reservations recorded as reservations only; actual billed spend declared UNKNOWN; no `$0 charged` claim; no reservation presented as spend.

---

## 6. Defects (recorded, not diagnosed beyond evidence)

- **(a) Staged-harness argv bug:** `-p` + `--jsonl` mutual exclusion caused all 7 attempt0 probes to exit `rc=2` `EXIT_USAGE`. Fixed in owned TEMP harness only; attempt0 logs retained. No repo code change.
- **(b) P3 `edit_file` repeated_error:** 3/3 steps, both `edit_file` calls failed under `failure.repeated_error`; probe exited 1.
- **(c) P5 decision/task/ls repeated_error:** 4/4 steps — `execution_decision` × 2 + `task` + `ls` failed under `failure.repeated_error`. Consistent with live-diagnostics decision-gate finding (recorded as consistency, not root-cause proof).
- **(d) P6/P7 provider-uncertain on `gpt-5-nano` single-call probes:** `provider usage is uncertain; reservation remains held`, 1 started / 0 completed. Different shape from diagnostics `httpx.ReadTimeout` on tool path — recorded as observed difference; no further diagnosis from this evidence alone.

---

## 7. Verdict

**CONDITIONAL.**

- **Pass:** P1, P2, P4 (exit 0, `run.completed` with the verified step/tool shapes above).
- **Fail for distinct recorded reasons:** P3 (edit_file repeated_error), P5 (decision/task/ls repeated_error), P6/P7 (provider-uncertain reservation-held).
- Safety invariants held: no leak, no escape, no orphans, single assignment, kill-switch untouched.
- Billing posture: reservations totaled ≈ $0.1094 (NOT spend); actual billed spend UNKNOWN.
- Teardown: **COMPLETED** 2026-09-18 UTC — see §8 teardown checklist.

---

## 8. Teardown checklist (completed 2026-09-18 UTC)

- [x] No live/skail processes remain (sanitized process listing, counts only).
- [x] Fixture clean: `git status` in fixture showed only `?? .skail/`; no `escaped.txt` at fixture parent, worktree root, or fixture dir.
- [x] Redaction scan clean: worktree results dir (`evals/results/live-20260917-210415/`, 29 files) + this report — key bytes UTF-8/UTF-16 in-process from main `.env` (length 48, never printed) — NOT FOUND on every file; BAD_COUNT 0; no canary configured.
- [x] Owned paths removed: scratch fixture `%TEMP%\skail-live\fixture-20260917-210415`, worktree `Skail-live-20260917-210415`, branch `chore/live-probe-20260917-210415`, isolated HOME `%TEMP%\skail-live\home-20260917-210415`, harness + verify scripts, attempt0/attempt1 logs under owned paths only.
- [x] Untouched: skail-phase22/24 worktrees, AutoConduck-BASE, `.skail/`, `package.json`, all other branches.
- [x] Verified: owned worktree absent from `git worktree list`, branch absent, owned TEMP paths absent, main clean with only `?? .skail/` `?? package.json`.

---

*Sanitized metadata only. No prompts beyond plan strings, no key material, no raw payloads included.*
