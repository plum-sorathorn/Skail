# AutoConduck Two-Plane Transformation — Complete Plan (v1.1)

**Status:** Approved — Phases 0-5 implemented (commits ea0e23b..HEAD); Phase 6 gates pending
**Date:** 2026-08-30
**Target state:** Proxy = pure turn-by-turn model router (+ ledger + control API). Plugin = optional orchestrator (thin per-harness shims + daemon-side Python runtime). Plugin off → byte-identical pure-router product.
**Audit directive (binding):** The local SLM (Qwen 0.5B) is an OPTIONAL, NON-BINDING signal — never an authority. Every plugin duty has a deterministic baseline; the routed LLM handles judgment; the plugin must remain fully functional if the SLM is useless.

---

## The Brain Ladder (binding for all plugin duties)

| Duty | Deterministic baseline (primary) | SLM role | Routed LLM role |
|---|---|---|---|
| Turn classification | Event type, tool/error counts, explicit user intent, tool/file history | Optional label refinement (non-binding) | Never required |
| Task contract generation | Fixed schema populated from request + harness metadata + declared constraints | Suggest missing fields only; cannot invent commitments | Generate/revise when contract ambiguous and high-value |
| Stagnation judgment | Exact repeated-call thresholds, consecutive-error counters, no-progress counters | **None** by default | Optional diagnosis after deterministic trigger fires |
| Quality/progress assessment | Completion criteria, test/build exit codes, diff/tool evidence, required-artifact checks | Summarize evidence only | Semantic evaluation when requested or deterministic checks insufficient |
| Final-output synthesis | Template from verified ledger facts + tool outcomes | Optional concise wording | Best-effort synthesis; unverified claims must be labeled |
| Escalation decisions | Explicit trigger matrix (failures, ambiguity, requested review, unmet acceptance checks) | Tie-breaker only after deterministic ambiguity | Select higher-capability model through the router |

**Never SLM-only:** escalation, stagnation detection, success/completion claims, tool safety/authorization, contract constraints, factual assertions in final output.
**SLM-failure posture:** schema-valid default contracts, deterministic event state machine, fixed error/repetition triggers, evidence-based completion checks, templated summaries — plugin fully functional with the SLM disabled.

## Phase 0 — Safety Net
1. Create branch `two-plane`; record baseline: `python -m pytest` results, `python scripts/end_to_end_smoke.py` result → `BASELINE.md` (repo root).
2. `graphify update .`.
3. **Commit 1 (BEFORE Phase 1):** plan doc v1.1 + BASELINE.md.

## Phase 1 — Proxy Strip-Down (green-per-commit; result: shippable pure router)

**1.1 Dispatcher (`routing/dispatcher.py`, 214 → ~150 lines):**
- Delete SLOW branches: `ESCALATE_SLM`→slow (:61-74), `replan_pending` (:76-94), `dynamic_dag` clean-turn branch (:118-127).
- Wire `task_type` + `confidence` into fast-branch selection (engage `TASK_TYPE_WEIGHTS` + confidence floor `min(base + 0.15*(1-conf), 0.60)` on every classified turn).

**1.2 Planner (`routing/slm_planner.py`, 832 → ~380 lines):**
- Delete: `SubTaskSpec`/`Phase`/`to_phase` (:155-189), plan-mutation machinery (:297-359), `create_escalation_plan` (:442-496), `evaluate_session_trajectory*` (:523-659), route decision logic (:707-736).
- Keep: `TaskClassification` (trim to `task_type`, `confidence`, `complexity_score`), `_raw_infer` (strip DAG rules), `normalize_confidence`, `sanitize_task_type`, `_create_fallback_plan`, circuit-breaker `plan()`, model loading, text extraction, noise stripping.

**1.3 Server layer:**
- `server_router.py`: remove SLOW handling, `__answer__` replacement, `_run_async_slm_heartbeat` (:47-100) + scheduling (:316-327), `escalation_plan` consumption.
- `server_chat.py`: remove DAG progress streaming; keep SSE model streaming.
- `messages_api.py`: stays; purge plan-injection references.
- `tui/dashboard.py:272`: remove SLOW counter.

**1.4 Deletions:** `orchestrator/dynamic_factory.py`, `handoff.py`, `fan_out.py`, `subagents.py`; `scripts/simulate_slow_path.py`; `tests/integration/test_simulations.py` SLOW-path tests; dead config keys: `ambiguous_low/high`, `escalation_threshold`, `slow_threshold`, `min_orchestrator_complexity`, `deescalation_threshold` — **config migration: deprecated keys in user config.yaml are tolerated with a startup warning, never a crash.** **Salvage first:** move `executor_loop.py` + `tools.py` into the new plugin runtime package. **`session_guard.py` gate:** audit BEFORE salvage — extract only proxy-facing prefix-immutability/compaction behind tests; do not carry DAG coupling into either plane.

**1.5 Green-per-commit (mandatory):** update/delete affected tests, smoke assertions, dashboard counter, and config-compat coverage IN THIS PHASE. `python -m pytest` must pass before the commit.

**1.6 Architecture clarification (binding):** orchestrator *brain lives in the daemon* (Python — reuses SLM, litellm, salvaged executor); per-harness *shims are thin sensors/actuators*. The brain cannot live in TypeScript shims.

→ *Verify: pytest green; router boots; smoke (router-only mode) passes; no code path rewrites a model's answer; zero references to deleted symbols.*
**Commit 2.**

## Phase 2 — Plugin Runtime (daemon-side, Python)

**2.1 Control surface:** `POST /plugin/events` (ingestion), `GET /plugin/contract?session=` (JSON task contract), `POST /plugin/escalate` (deterministic trigger matrix → selection-bias update).
**2.2 Ledger:** SQLite (WAL) under `~/.autoconduck/run/`. **Writes are async: in-memory bounded queue, batched transactions (size/time threshold), drop/coalesce non-critical telemetry under pressure. Durable events only: task start, escalation, terminal result, errors.** Correlation IDs per session/task; retention limit; no prompt content stored by default (privacy).
**2.3 Orchestrator runtime:** salvaged `executor_loop`+`tools` = internal subagent execution (proof path); SLM per Brain Ladder only; LLM escalation dispatched through the router (dogfooding).
**2.4 Escalation bias semantics:** session/task correlation ID → proxy applies raised floor to subsequent selections for that session; defined TTL, precedence, reset-on-new-turn; honest scope — harness-native loops get next-request bias only; internal executor gets true in-loop escalation.
**2.5 Synthesis:** templated final output from ledger facts (deterministic); LLM synthesis stubbed behind config, off by default.
**2.6 Daemon lifecycle:** lockfile, crash recovery (ledger is authoritative), port/socket collision handling; plugin endpoints fail-soft no-op when `plugins.enabled=false`.

→ *Verify: ledger lifecycle test; escalation bias changes next-turn selection; plugin-disabled = endpoints no-op; SLM-disabled = deterministic baseline still completes a task.*
**Commit 3.**

## Phase 3 — Per-Harness Shims (thin, toggled by `plugins.enabled`)

**3.1 Hook protocol (binding):** shims are NON-BLOCKING. Localhost append to bounded queue with 5–10ms timeout, then drop on failure; never await planning, ledger writes, or LLM calls; local overhead budget <10ms per hook invocation.
**3.2 Claude Code (the one shipped shim):** `hooks` block added by existing `patch()` → `autoconduck hook claude <event>`; PreToolUse/PostToolUse/Stop → fire-and-forget events; observe-only in v1 (no blocking decisions).
**3.3 Pi / OpenCode:** stubbed behind disabled flags (`plugins.pi.enabled=false`, `plugins.opencode.enabled=false`) — install machinery present, hooks inert; full implementation deferred.
**3.4 OMP:** deferred entirely.

→ *Verify: shim install/uninstall clean; disabled state = zero behavioral delta; hook overhead measured <10ms; daemon-down → shim silent no-op.*
**Commit 4.**

## Phase 4 — Tests, Smoke, Tooling
1. `end_to_end_smoke.py`: mode A (router-only), mode B (router+plugin with deterministic-only orchestration).
2. Unit suites: stripped dispatcher (incl. fast-branch floor tightening), trimmed classifier, ledger batching/WAL, escalation bias TTL/reset, shim contracts, config migration warnings.
3. Packaging: `python npm-packaging/build.py --check` verifies wheels include new files.
4. `graphify update .`.
→ *Verify: pytest green; both smoke modes pass.*
**Commit 5.**

## Phase 5 — Documentation Alignment (BEFORE acceptance + audit)
Update ALL documents to match the shipped reality: `README.md` (two-plane architecture, toggle, removed DAG/thresholds — delete dead-config documentation), `AGENTS.md` (new structure, invariants preserved: fail-soft, Turn Guard, selection, markers; plugin runtime + brain ladder), `TWO_PLANE_PLAN.md` status header, every file under `docs/` (design docs, CHANGELOG entry), CLI/TUI references.
→ *Verify: grep for removed symbols/thresholds across docs returns zero stale hits; docs describe only existing behavior.*
**Commit 6.**

## Phase 6 — Acceptance Gates
- Routing hot path sub-ms; Turn Guard <2ms (benchmark script, numbers recorded).
- Plugin-off routing byte-identical to post-strip router; functionally equal to today's fast path.
- Fail-soft matrix: SLM timeout → fallback selection; shim↔daemon loss → inert shim; ledger I/O error → routing unaffected; config with removed keys → warning only. Never a 500.
- Version bump (`python scripts/bump_version.py --minor`) only after gates pass.
→ *Verify: gate script output recorded in BASELINE.md appendix.*
**Commit 7.**

## Phase 7 — Full Alignment Audit & Refactor (activates after Phase 6)

Principal-architect audit with zero shortcuts, four phases:
1. **Vision & Intent Reconstruction** — re-read ALL updated docs/schemas/entrypoints; state the core problem, target architecture (two-plane router+orchestrator with deterministic-first brain ladder), and non-negotiable invariants (fail-soft, <2ms Turn Guard, sub-ms selection, marker-bounded config edits, mirrored requirements, SLM-never-authority).
2. **Exhaustive Codebase Audit** — every active source file mapped against the vision; flag stale/legacy code, erroneous/divergent logic (races, error bubbling, state transitions), architectural drift (leaky boundaries, duplicate responsibilities). Batched read-only sweeps until zero unread files.
3. **Structured Remediation Plan** — dependency-ordered removals / refactors / fixes before any modification.
4. **Implementation & Verification** — purge dead weight completely, align every component to the two-plane intent, harden typing/error handling/determinism, run tests + cover previously erroneous edge cases, validate end-to-end.

**Commit 8 (final).**

---

**Execution order:** Phase 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7. Commit before Phase 1 and after every phase. Each phase ends shippable and green.
**Overnight scope guard:** v1 ships = stripped router + ledger + deterministic orchestration + ONE shim (Claude Code) + internal executor proof path. Subagent deployment policy engine, semantic quality judging, LLM synthesis, Pi/OpenCode full shims: stubbed/deferred — never half-wired.
