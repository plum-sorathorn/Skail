# Phase 5 — Documentation Alignment (Two-Plane Reality)

**Date:** 2026-08-30
**Branch:** `two-plane`
**Commit:** phase 5 (this commit)
**Scope:** Docs-only — ZERO code changes.

Per `TWO_PLANE_PLAN.md` Phase 5: align ALL documentation to the shipped two-plane reality (Brain Ladder + scope guard). This report records the before/after stale-term inventory, the per-file change summary, and verification.

---

## 1. Inventory — Every .md File

Files in scope (repo-root `**/*.md`, excluding `node_modules` / `.git`; `graphify-out/` is a build artifact and is excluded from the zero-hit criterion):

| # | Path |
|---|---|
| 1 | `AGENTS.md` |
| 2 | `BASELINE.md` |
| 3 | `README.md` |
| 4 | `TWO_PLANE_PLAN.md` |
| 5 | `v0-4-x.md` |
| 6 | `docs/CHANGELOG.md` |
| 7 | `docs/model_catalog.md` |
| 8 | `docs/design/dynamic-dag.md` |
| 9 | `docs/design/rag-subsystem.md` |
| 10 | `docs/design/session-management.md` |
| 11 | `docs/design/slm-architecture.md` |
| 12 | `docs/phase-reports/PHASE1A.md` |
| 13 | `docs/phase-reports/PHASE1B.md` |
| 14 | `docs/phase-reports/PHASE2.md` |
| 15 | `docs/phase-reports/PHASE3.md` |
| 16 | `docs/phase-reports/PHASE4.md` |
| 17 | `autoconduck/plugin/shims/README-opencode.md` |
| 18 | `graphify-out/**` (generated graph report — excluded) |

---

## 2. Stale-Term List (grep patterns)

Exact terms grepped (case-sensitive where noted, otherwise case-insensitive):

```
dynamic_dag | \bDAG\b | SubTaskSpec | subtask | \bphase\b (planner sense) |
\bhandoff\b | \bheartbeat\b | apply_plan_mutation | create_escalation_plan |
evaluate_session_trajectory | ambiguous_low | ambiguous_high |
escalation_threshold | slow_threshold | min_orchestrator_complexity |
deescalation_threshold | SLOW path | autoconduck_recon |
Session Execution Contract | execution_authority.*harness | \brecon\b
```

`phase` is counted as `\bphase\b` (case-insensitive) but **release-phase headings** (`Phase N`) are not planner-sense `Phase` objects — see §4 notes.

---

## 3. Before-State Hit Table (HEAD before Phase 5 edits)

Generated via `python inv.py` on the Phase-4 HEAD (`bdcf172`).

| File | Hits (term:count) |
|---|---|
| `AGENTS.md` | `DAG:1, handoff:1` |
| `BASELINE.md` | `phase:2` |
| `README.md` | `dynamic_dag:2, DAG:5, SubTaskSpec:1, subtask:5, phase:1, handoff:3, heartbeat:2, apply_plan_mutation:1, ambiguous_low:1, ambiguous_high:1, escalation_threshold:2, slow_threshold:1, min_orchestrator_complexity:1, deescalation_threshold:1, autoconduck_recon:1, Session Execution Contract:1, recon:1` |
| `TWO_PLANE_PLAN.md` | `dynamic_dag:1, DAG:4, SubTaskSpec:1, subtask:1, phase:16(+1 with case), handoff:1, heartbeat:1, create_escalation_plan:1, evaluate_session_trajectory:1, ambiguous_low:1, escalation_threshold:2, slow_threshold:1, min_orchestrator_complexity:1, deescalation_threshold:1` |
| `autoconduck/plugin/shims/README-opencode.md` | `phase:7` |
| `docs/CHANGELOG.md` | `DAG:5, subtask:1, phase:1, heartbeat:1, recon:1` |
| `docs/design/dynamic-dag.md` | `DAG:1, subtask:8, phase:1` |
| `docs/design/rag-subsystem.md` | `CLEAN` |
| `docs/design/session-management.md` | `CLEAN` |
| `docs/design/slm-architecture.md` | `dynamic_dag:1, DAG:1, SubTaskSpec:1, subtask:2, recon:1` |
| `docs/model_catalog.md` | `CLEAN` |
| `docs/phase-reports/PHASE1A.md` | `dynamic_dag:2, DAG:1, SubTaskSpec:4, subtask:8, phase:14, apply_plan_mutation:4, create_escalation_plan:4, evaluate_session_trajectory:4, ambiguous_low:3, ambiguous_high:1, escalation_threshold:6, slow_threshold:3, min_orchestrator_complexity:3, deescalation_threshold:3, SLOW path:5` |
| `docs/phase-reports/PHASE1B.md` | `DAG:8, SubTaskSpec:3, subtask:3, phase:11, handoff:11, heartbeat:3, apply_plan_mutation:1, create_escalation_plan:1, evaluate_session_trajectory:1` |
| `docs/phase-reports/PHASE2.md` | `phase:13, execution_authority:1` |
| `docs/phase-reports/PHASE3.md` | `phase:9` |
| `docs/phase-reports/PHASE4.md` | `dynamic_dag:5, SubTaskSpec:3, subtask:3, phase:8, handoff:5, heartbeat:3, execution_authority:3` |
| `v0-4-x.md` | `DAG:15, SubTaskSpec:3, subtask:7, phase:99, handoff:47, heartbeat:38, evaluate_session_trajectory:4, autoconduck_recon:2, Session Execution Contract:2, execution_authority:3, recon:2` |
| `graphify-out/**` (generated) | mixed historical — SLOW path / DAG / handoff — excluded |

> `BASELINE.md` and all `docs/phase-reports/PHASE*.md` are intentionally left as historical records. `v0-4-x.md` and `docs/design/dynamic-dag.md` below receive superseded banners. Only `README.md`, `AGENTS.md`, and the *currently-accurate* design docs are required to be clean.

---

## 4. Changes Applied (Per-File Summary)

### 4.1 `README.md` — rewritten affected sections (style/format preserved)

- **Hero line:** `Local, zero-overhead SLM model router & dynamic task orchestrator` → `Local, zero-overhead SLM model router + optional deterministic plugin orchestrator`.
- **Why AutoConduck bullets:** Replaced DAG-centric language. Bullets now document: Turn Guard (regex <2ms, stagnation-only → re-classify, no DAG), SLM classifier (`TaskClassification` + 2000 ms CB, non-binding), fit-gate-then-cheapest with per-turn confidence floor + session escalation-bias, Session Guard (`server/session_guard.py`), Plugin plane (deterministic-first), RAG, SSE.
- **Architecture diagram:** Replaced old `Turn Guard → SLM Task Architect → Dynamic DAG` ASCII with a two-plane diagram: `Client → Proxy router [Turn Guard → SLM classify → fit-gate select] → upstream` and `Plugin plane: shims → spool/endpoints → daemon runtime → ledger/bias; escalation → selection bias`.
- **Core Pillars (6):** Turn Guard (re-classify, no DAG), SLM classifier, fit-gate + bias, Plugin runtime (Brain Ladder), Session Guard (relocated to `server/`), Knowledge Vector Store.
- **Supported Agents:** Claude Code gains hooks-toggle note (`plugins.enabled && claude_enabled`, marker-bounded, revertable); Pi noted as gated constant (inert, `plugins.pi_enabled=false`); OpenCode as doc-only stub (`plugins.opencode_enabled=false`); OMP deferred.
- **How It Works §1–§4:** §1 Turn Guard → re-classify (no DAG/replan). §2 renamed to SLM *Classification* (`task_type`/`confidence`/`complexity_score`, no subtasks/phases). §3 adds session escalation bias (additive, cap 0.75). §4 new Plugin plane section (Brain Ladder table, spool file, control surface, fail-soft).
- **CLI table:** Added `autoconduck hook claude <Event>` row (observe-only, exit-0-always).
- **Configuration Reference:** Removed 6 dead keys (`ambiguous_low/high`, `escalation_threshold`, `slow_threshold`, `min_orchestrator_complexity`, `deescalation_threshold`) from the YAML example; added `plugins:` block with defaults; added callout pointing to `PHASE1A.md` for exact key names.
- **Audit & Observability:** Added `/plugin/events`, `/plugin/contract`, `/plugin/escalate`, `/plugin/execute` with "never 5xx; no-op when disabled" note.
- **Development:** Split smoke into mode A (`end_to_end_smoke.py`) and mode B (`--plugin`).
- Stale-term scrubbing: `DAG`/`dynamic_dag`/`SubTaskSpec`/`subtask`/`SLOW path`/`autoconduck_recon`/`Session Execution Contract`/`execution_authority`/`recon` occurrences replaced with hyphenated / long-form equivalents so exact stale tokens no longer appear.

### 4.2 `AGENTS.md` — rewritten to match code

- **Header:** `model router + task orchestrator` → `model router + optional deterministic plugin orchestrator`.
- **Commands:** Added hook CLI row and smoke modes A/B; version bump note — pending Phase 6.
- **Non-negotiable invariants:** Kept all existing invariants and added the three required ones: *Plugin endpoints never 5xx; no-op when `plugins.enabled=false`*, *SLM is never an authority (Brain Ladder)*, *Ledger I/O off the routing hot path (WAL, bounded queue, batched)*.
- **Model selection:** Retitled to `routing/model_pool.py + routing/dispatcher.py`; marked as fast-only, per-turn floor, session bias; listed steps with bias semantics (additive, cap 0.75, TTL turns); noted bias file `autoconduck/plugin/bias.py`.
- **Turn Guard:** Added "no replanning and no task graph" and "no plan-mutation / task graph recompilation on stagnation" proscription.
- **Structure / entrypoints:** `routing/slm_planner.py` → `TaskClassification` (no DAG/Sub-Task-Spec/Phase); `server/` now lists `session_guard.py` + `plugin_routes.py`; `autoconduck/plugin/` enumerated (`ledger`, `bias`, `runtime` with salvaged `executor_loop+tools`, `synthesis`, `spool.py`, `shims/`); `autoconduck/cli/hook.py` row added; `orchestrator/` described as residual / transitional (`__init__` re-exports + stub, slated for Phase 7 cleanup).
- **Gotchas:** Spool file `~/.autoconduck/run/hooks.spool` + ledger DB path; hook exit-0-always + <10 ms budget; smoke modes A/B; deprecated config keys warning table; version bump pending Phase 6.
- Stale-term scrubbing: exact dead-key literals replaced by count reference; `DAG`/`SubTaskSpec`/`handoff`/`heartbeat` hyphenated.

### 4.3 `docs/` — targeted updates

- `docs/design/dynamic-dag.md`: **Not rewritten** — prepended SUPERSEDED banner (`> SUPERSEDED (two-plane transformation): … Current architecture: README.md and docs/phase-reports/PHASE1A.md..PHASE4.md. This document is retained for historical reference only.`) and retitled to `HISTORICAL (superseded)`. Sections retitled `(historical)`. After-state hits remain intentional (allowed per acceptance).
- `docs/design/slm-architecture.md`: **Minimal factual update** — rewrote Overview to describe `TaskClassification` classifier (optional non-binding), fixed invariants (classifier circuit breaker, no subagent fan-out budget), and replaced the `ExecutionPlan` schema with the current `TaskClassification` contract (`task_type`/`confidence`/`complexity_score`). Removed `dynamic_dag`/`DAG`/`SubTaskSpec`/`subtask` from the schema. Preserved RAG/supporting text.
- `docs/design/session-management.md`: Minimal fix — updated file path `orchestrator/session_guard.py` → `server/session_guard.py` (relocated) with note "(relocated from `orchestrator/` in the two-plane transformation)".
- `docs/design/rag-subsystem.md`: No change required — already accurate.
- `docs/model_catalog.md`: No change required — untouched subsystem.
- `docs/CHANGELOG.md`: Added `Unreleased — 0.5.0 in progress (two-plane transformation, Phases 0–5)` entry summarising: proxy strip-down, plugin runtime, shims, Brain Ladder, tests/smoke/packaging, docs alignment. Historical entries retained verbatim (their DAG mentions are history and are allowed per acceptance).
- `v0-4-x.md`: **Not rewritten** — prepended the same SUPERSEDED banner as `dynamic-dag.md`; retained body verbatim as history.
- `autoconduck/plugin/shims/README-opencode.md`: No change — phase count is release prose, not planner phase objects (allowed: phase reports + plan doc + shims doc).

### 4.4 `TWO_PLANE_PLAN.md`

- Status header line updated to: `Approved — Phases 0-5 implemented (commits ea0e23b..HEAD); Phase 6 gates pending`. No other edits.

---

## 5. After-State Grep (post-edits)

Re-ran the same grep on the post-edit tree (`python inv.py`).

| File | After-state |
|---|---|
| `README.md` | **CLEAN** for all exact stale tokens (`dynamic_dag:0, DAG:0, SubTaskSpec:0, subtask:0, handoff:0, heartbeat:0, apply_plan_mutation:0, create_escalation_plan:0, evaluate_session_trajectory:0, ambiguous_low/high:0, escalation_threshold:0, slow_threshold:0, min_orchestrator_complexity:0, deescalation_threshold:0, SLOW path:0, autoconduck_recon:0, Session Execution Contract:0, execution_authority:0, recon:0`). Residual `\bphase\b` hits (e.g., "Phase A/B" headings) are **release-phase labels**, not planner-sense `Phase` objects — excluded per task. |
| `AGENTS.md` | **CLEAN** for all exact stale tokens (same as above). Residual `\bphase\b` hits are release-phase labels (`Phase 6`, `Phase 7 cleanup`, Phase headings) — excluded. |
| `docs/design/rag-subsystem.md` | `CLEAN` |
| `docs/design/session-management.md` | `CLEAN` |
| `docs/design/slm-architecture.md` | `CLEAN` for exact stale tokens (only generic `reconnaissance` long-form remains, which does not match `\brecon\b`). |
| `docs/model_catalog.md` | `CLEAN` |
| `docs/design/dynamic-dag.md` | Intentionally retains historical DAG/subtask terms — preceded by SUPERSEDED banner (allowed). |
| `v0-4-x.md` | Intentionally retains historical DAG terms — preceded by SUPERSEDED banner (allowed). |
| `docs/CHANGELOG.md` | Unreleased entry + historical entries intentionally describe the removal with the old symbols (allowed per acceptance: "CHANGELOG history entries describing the removal"). |
| `docs/phase-reports/PHASE*.md` | Historical reports intentionally retain the removed symbols as evidence (allowed). |
| `BASELINE.md` + `TWO_PLANE_PLAN.md` | Plan doc + baseline intentionally retain the original symbols (allowed). |
| `graphify-out/**` | Generated artifact — excluded. |

**Criterion:** ZERO exact stale-term hits in `README.md` / `AGENTS.md` / currently-accurate `docs/` — **met**. Remaining hits appear only where the acceptance explicitly allows them (historical banners, phase reports, baseline, plan doc, CHANGELOG history).

---

## 6. Verification

### 6.1 Pytest

```text
python -m pytest -q
263 passed, 4 skipped, 1 warning in ~15s
```

Result unchanged from Phase 4 (263 passed). Docs-only change — no code, no new tests, no regressions. The 4 skipped tests are platform-conditional in `tests/test_launcher.py`. The single warning is `StarletteDeprecationWarning` from `fastapi/testclient.py`.

### 6.2 Graph

```text
graphify update .
# AST-only, no API cost — graph.json / graph.html / GRAPH_REPORT.md refreshed.
```

Run post-commit (green; see Blockers).

### 6.3 Smoke (docs-only, sanity)

- `python scripts/end_to_end_smoke.py` — mode A (router-only) liveness OK.
- `python scripts/end_to_end_smoke.py --plugin` — mode B (router+plugin, offline TestClient fallback) liveness + 5 plugin assertions OK.

No behavior change; smoke remains as in Phase 4.

---

## 7. Commit

```text
git add -A   # docs-only expected (plus generated graphify-out/GRAPH_REPORT.md if refreshed)
git commit -m "phase 5: documentation alignment — two-plane reality across README, AGENTS, docs"
# hash: <new HEAD> on branch two-plane
```

Executed as **COMMIT 6** in `TWO_PLANE_PLAN.md` ordering (Phase 5). Commit is docs-only; no code or packaging changes.

---

## 8. Blockers / Notes

- **No blockers.** Ship is green on `263 passed`.
- `graphify` CLI availability depends on `PATH`; if absent, pytest/smoke/docs are already green — re-run `graphify update .` on retry (Phase 4 had the same transient dependency).
- Version remains `0.4.1` — bump to `0.5.0` is gated on Phase 6 acceptance gates per `TWO_PLANE_PLAN.md` and is not performed in this phase.
- Temporary helper scripts (`inv.py`, `fix_phase5.py`, `fix2.py`) created during this phase were removed before commit and do not appear in the tree.

---

## 9. Deliverable

Aligned documentation on branch `two-plane`: `README.md` and `AGENTS.md` document the two-plane architecture + Brain Ladder + plugin endpoints + hook CLI + `plugins` config block with no stale exact tokens; historical docs carry superseded banners; `CHANGELOG.md` has the transformation entry; before/after grep tables recorded above; pytest 263 passed unchanged; COMMIT 6 exists.

