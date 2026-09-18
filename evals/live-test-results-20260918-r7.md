# Live Test Results — 2026-09-18 R7

**Run ID:** live-20260918-r7
**Date (UTC):** 2026-09-18
**Branch:** `skail-tui-rework` @ `7172bde` (P5 ran) / report committed on `99a2d6b`
**Report file:** `evals/live-test-results-20260918-r7.md`
**Mode:** live probe P5 (lead-isolation) via owned harness — NO live calls made during
report writing; NO code changes in this task.
**Teardown:** COMPLETED inline (see §8).

---

## 1. Environment

| Field | Value |
|---|---|
| OS | Windows 11 |
| Repo | `C:\Users\plum\Documents\Works\Skail`, branch `skail-tui-rework` @ `7172bde` at probe time |
| Code under test | `7172bde` (lead-direct-write block in worktree mode; guidance fix `99a2d6b` landed after) |
| Worktree | `Skail-live-r7-20260918-012829` @ `7172bde` (branch `chore/live-probe-20260918-012829`) |
| Fixture baseline | `fixture-20260918-012829` (post-run: clean — only `?? .skail/`) |
| Isolated HOME | isolated HOME (config + trust db only) |
| Credential handling | `LLMGATEWAY_API_KEY` env-only, length 48; no key material in logs or report |
| Secret scans | key-bytes UTF-8/UTF-16 NOT FOUND, canary NOT FOUND on both logs + this report |
| Escape check | absent — no `escaped.txt` at fixture dir or worktree root |

Probe run: **P5 only** (lead-isolation on worktree), mini lead, cap $1.25.
Two invocations: original attempt + 1 plan-allowed transient retry.

Notes:

- No prompts reproduced beyond plan strings (already public in plan). No key material. No raw payloads.
- `budget.reserved` strings below are already-recorded sanitized amounts (reservations, NOT spend).

---

## 2. Budget ledger

| Probe | Calls | Est. cost | Provider actual | Reserved after | Cumulative upper bound |
|---|---|---:|---:|---:|---:|
| P5 attempt 1 | 16 models | UNKNOWN (no usage fields) | UNKNOWN | 0.044611 | 0.044611 |
| P5 attempt 2 (final) | 9 models | UNKNOWN (no usage fields) | UNKNOWN | 0.044611 | 0.089222 |

- Sum of per-attempt reservations: **2 × 0.044611 = 0.089222** (reservation, NOT spend).
- Kill-switch **$13.50** untouched.
- No `usage` / token keys in either JSONL; all billed-spend deltas null/absent.
- Actual billed spend **UNKNOWN** — never claim $0 charged, and never present any
  reservation figure as spend.

---

## 3. Probe results

| ID | Mode | Route/assignment IDs | Attempts/peak children | TTFT/E2E | Outcome | Checks | Evidence path |
|---|---|---|---:|---:|---|---|---|
| P5 attempt 1 | live, worktree | route.selected present | 1 attempt / 0 children | E2E 27.4 s (05:48:15–05:48:42Z) | `run.blocked` (`plan.node_blocked`), rc=3 | 16/16 models; `plan.admitted` + node admitted/launching/running/blocked | `logs-20260918-012829/p5-014809.jsonl` (72 lines) |
| P5 attempt 2 | live, worktree (retry) | route.selected present | 1 attempt / 0 children | E2E 18.8 s (05:48:47–05:49:06Z) | `run.completed`, rc=0 | 9/9 models; 0/10 tools completed | `logs-20260918-012829/p5-014844.jsonl` (43 lines) |

Attempt 1 tool detail (verified by-type counts):

- `tool.started`: execution_decision × 5, grep × 2, read_file × 3, task × 5 (15 total).
- `tool.completed`: execution_decision × 1, grep × 2, read_file × 3, task × 5 (11 total).
- `tool.failed`: execution_decision × 4 (payloads carry tool name + status only).
- Plan chain: `plan.admitted` → `plan.node_admitted` → `plan.node_launching` →
  `plan.node_running` → `plan.node_blocked` → `run.blocked`.

Attempt 2 tool detail (verified):

- `tool.started` = `tool.failed` = 10 (execution_decision × 3, grep × 3, task × 4);
  `tool.completed` = 0. Zero children spawned. `run.completed`.

Cross-attempt invariants:

- Zero children spawned on both attempts.
- Billing honesty: reservations recorded as reservations only; billed spend UNKNOWN.
- Safety scans: key/canary NOT FOUND on both logs; escape absent.
- Fixture post-run clean (`git status`: only `?? .skail/`); 0 changeset events in both
  logs — no lead bypass observed, but also no positive integration proof.

---

## 4. Performance

| Metric | Samples | Median | p95/max | Threshold | Result |
|---|---|---:|---:|---|---|
| P5 attempt E2E | 2 | — | 27.4 s max | none set (probe) | recorded only |
| Log volume | 2 | — | 72 / 43 lines | n/a | recorded only |

- Attempt 1 E2E 27.4 s; attempt 2 (retry) E2E 18.8 s.
- No warm-start re-measurement in R7 (out of scope per task constraints).

---

## 5. Safety / invariant evidence

- Assignment stickiness: no assignment-change evidence in either log (single attempt each).
- Maximum child attempts / peak concurrency: 0 children on both attempts (limit respected).
- Writer lease/worktree isolation: fixture clean post-run; 0 changeset events; no `escaped.txt`
  at fixture or worktree root — **no bypass observed**.
- Approval/trust decisions: none recorded (no destructive/external actions attempted).
- Secret/canary scan (FOUND/NOT FOUND only): key-bytes UTF-8 **NOT FOUND**,
  key-bytes UTF-16 **NOT FOUND**, canary **NOT FOUND** (both logs + this report).
- Session resume/export reconciliation: not exercised in R7 (P5 only).

---

## 6. Defects

| Severity | Reproduction | Expected | Actual | Session/run/event IDs | Sanitized evidence |
|---|---|---|---|---|---|
| n/a (no new product defect) | — | — | — | — | R7 is a NO-OP verdict; root causes below are already fixed in `99a2d6b` |

Root-cause analysis (code-cited, recorded for the verdict — fixes already landed):

1. **Initial guidance never showed the ExecutionPlan schema → mini invents
   steps/tasks/id/type → repairs burn.** The lead prompt's guidance section did not
   include the plan/decision shape, so the mini lead generated non-conforming decisions
   that failed admission and burned repair rounds. **Fixed in `99a2d6b`** (minimal planned
   decision skeleton added to guidance; the scripted skeleton now admits first-try offline).
2. **Retry's 3 greps + 4 tasks failed via the decision gate — same admission failure,
   not separate bugs.** With no admitted decision, downstream `grep`/`task` calls fail at
   the execution decision gate (`execution.decision_required` / task pre-spawn path checks).
   Attempt 2's 0/10 tool success is the consequence of (1), not independent tool breakage.
3. **Attempt 1's `node_blocked`: one plan node settled blocked** (routing/budget/validation/
   command gate), not an all-models failure — 16/16 models completed and 11/15 tools
   completed before the single admitted node blocked.

---

## 7. Verdict

- **P5 R7: NO-OP** — attempt 1 loud-blocked with real work done (11 tools completed,
  full plan chain to `node_blocked`); final retry attempt completed with zero tool success.
- Isolation: **no bypass observed** — fixture clean, 0 changeset events, no `escaped.txt`,
  0 children, key/canary scans clean.
- Total live cost (larger of actual/estimate): **UNKNOWN** (no usage fields; reservations
  0.089222 are NOT spend).
- Unresolved warnings: billed spend unknowable from JSONL (pre-existing provider-reporting
  limitation, not new); positive integration proof absent (fixture untouched either way).
- **PASS / CONDITIONAL PASS / FAIL: NO-OP (neither pass nor fail)** — no release/security
  blocker, no functional proof either direction; root causes already fixed in `99a2d6b`,
  re-probe recommended on the fixed code.

---

## 8. Teardown checklist (COMPLETED — inline in this task, 2026-09-18)

- [x] No live/skail processes remain (0 python processes with `skail-live-r7` command line;
      0 python processes total at teardown).
- [x] Fixture status recorded (clean — only `?? .skail/`) before removal.
- [x] Redaction scan clean on both logs + this report (key bytes UTF-8/UTF-16 NOT FOUND,
      canary NOT FOUND; no unprovable files).
- [x] Owned paths removed: worktree `Skail-live-r7-20260918-012829`, branch
      `chore/live-probe-20260918-012829`, fixture `fixture-20260918-012829`, isolated HOME
      `home-20260918-012829`, logs `logs-20260918-012829`, runner script
      `run-p5-20260918-012829.py` + check script `check-p5r7.ps1` (+ verify helpers).
- [x] Verified: owned worktree absent from `git worktree list`, owned branch deleted, owned
      TEMP paths absent; main status only `?? .skail/` + `?? package.json` (pre-existing,
      untouched).
- [x] Untouched: all `skail-phase22*` / `skail-phase24*` worktrees, `AutoConduck-BASE`,
      `.skail/`, `package.json`, all other branches.

---

*Sanitized metadata only. No prompts beyond plan strings, no key material, no raw payloads included.*
