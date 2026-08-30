# Phase 7C Batch 1 — Correctness Fixes

Branch `two-plane` · v0.5.0 · 2026-09 batch. **Do not commit** per task instructions.

## Summary

270 passed, 4 skipped (was 263 passed before batch). All 8 audit items addressed.

## Per-fix Notes

### R1 — stats.py accounting revival
- **Finding:** `stats.py:147 pricing.record_usage` and `stats.py:89 pricing._entry` do not exist; both swallowed by bare `except:pass` → `stats.jsonl` never written, `estimate_cost` always 0.
- **Fix (smallest diff):** Keep call site; do not add `record_usage` to pricing (larger contract surface). Instead isolate the optional call: `fn = getattr(pricing,"record_usage",None); if callable(fn): fn(...)` inside its own try, so jsonl path always proceeds. Rewrite `estimate_cost` to consult real catalog: first `ModelPool(cfg)._get_model_entries()` (covers user-defined + preset merge + seeded defaults), then `curated_model_catalog()` (dedup litellm costs), then `_ingest_litellm_costs()` fallback. Compute `(prompt*price_in + completion*price_out)/1e6`.
- **Files:** `autoconduck/stats.py`
- **Test:** `tests/test_phase7c1_batch1.py::test_r1_estimate_cost_nonzero_and_record_writes_jsonl` (uses tmp `home_dir`, asserts cost>0 for `gpt-4o-mini` ~0.00045, then `record()` → `flush_stats()` → jsonl line written and parseable). Second test proves fail-soft when `record_usage` absent.

### R2 — server_router.py dead branch
- **Finding:** `from autoconduck.routing.pricing import pool_ids, select_closest` — `select_closest` never existed; `ImportError` swallowed → fallback never used.
- **Fix:** Remove dead branch entirely. Empty-model fallback is `resolve_orchestrator_model(cfg)` only.
- **Files:** `autoconduck/server/server_router.py:208-225`

### R3 — config/manager.py validate_phase_bands + phase_bands key
- **Finding:** Dead validation using nonexistent `pricing.scaled_cost`; `SelectionConfig.phase_bands` unused except by `orchestrator/planner.py` which is scheduled for deletion in Batch 2.
- **Decision (keep green):** Remove `validate_phase_bands()` and its call site + `phase_bands` field from `SelectionConfig` now. To keep green, also fix the sole consumer `orchestrator/planner.py::_select_planner_model` — it previously read `config.selection.phase_bands["planner"]` and called `pricing.select_closest(pool_ids, scaled_cost band)`. Replaced with fail-soft direct path: respect `planner_model_override` and `planner_retry_cheaper → cheapest_enabled` if present, else `resolve_orchestrator_model`. Removed `validate_phase_bands` re-export from `autoconduck/config/__init__.py`. Remaining `max_file_read_scaled_cost` / `fast_path_max_scaled_cost` are scalars, not the `scaled_cost` function, so retained. Comments mentioning `scaled_cost`/`phase_bands` scrubbed.
- **Files:** `autoconduck/config/manager.py`, `autoconduck/config/models.py`, `autoconduck/config/__init__.py`, `autoconduck/orchestrator/planner.py`

### R4 — dispatcher.py price-cap tier dead (tier=None always)
- **Finding:** `_select_planned(..., tier=None)` always → `path_price_cap_usd_per_mtok` never consulted.
- **Fix:** Add `_tier_from_pseudo(pseudo_model) -> "budget"|"expensive"|"default"` (suffix `-budget` / `-expensive` / bare aliases). Wire at both `route()` call sites (`ESCALATE_SLM` and normal `else`), leave `DIRECT_ACTIVE_TIER` branch untouched (it uses `pricing.select_for_sla_detailed` directly). `_select_planned` itself already honors `tier` → `ceiling = path_price_cap...[tier]`. Default `{}` behavior unchanged.
- **Files:** `autoconduck/routing/dispatcher.py`
- **Test:** `test_r4_tier_derivation` with three caps (0.5/5.0/100.0) proves budget restricts, expensive picks most-expensive via pseudo_model hint.

### R5 — slm_planner.py plan_sync circuit breaker
- **Finding:** Sync path (`plan_sync` used by dispatcher hot path) had no timeout; breaker only in unused async `plan()`. Invariant violation.
- **Fix:** Reused single-thread `ThreadPoolExecutor(max_workers=1)` singleton (`_SLM_EXECUTOR`, `_SLM_EXECUTOR_LOCK`, `_get_slm_executor()`). `plan_sync` submits `_raw_infer` and does `future.result(timeout=slm_circuit_breaker_timeout_ms/1000)` (config or `self.circuit_breaker_ms`). On `TimeoutError` or any exception returns `_create_fallback_plan`. Docstring notes ONNX thread is abandoned on timeout (cannot be killed) — route proceeds fail-soft. Executor is global, not per-call.
- **Files:** `autoconduck/routing/slm_planner.py`
- **Test:** `test_r5_plan_sync_circuit_breaker_timeout_returns_fallback` monkeypatches `_raw_infer` with `sleep(0.5)` and `timeout_ms=50`, asserts fallback within 300ms. Companion success test confirms non-timeout path still works.

### R6 — Bias TTL double-increment
- **Finding:** `plugin_routes.py:_events_handler` incremented `get_bias_store().increment_turn(session_id)` on every plugin event, burning TTL turns outside the request path. `server_router.route_target` also increments per request → double counting.
- **Fix:** Remove the `increment_turn` block from `plugin_routes._events_handler` only; keep `server_router.route_target` increment as canonical per-request TTL advance.
- **Files:** `autoconduck/server/plugin_routes.py`
- **Test:** `test_r6_bias_ttl_not_incremented_by_plugin_events` asserts `increment_turn` not in `_events_handler` source but still in `route_target`.

### R7 — server_messages.py 500 leak (fail-soft violation)
- **Finding:** `handle_messages` line `except Exception: return JSONResponse(..., 500)` for `route_target` failure. Only place in codebase that 500s on router-internal failure.
- **Fix:** Mirror upstream 502 degrade: catch, log warning, resolve fallback model via `resolve_orchestrator_model`, return `JSONResponse(..., 502)` — never 500.
- **Files:** `autoconduck/server/server_messages.py`
- **Test:** `test_r7_route_target_failure_never_500` monkeypatches `route_target_fn` to raise, asserts response is 502 not 500.

### R8 — Harness render_plan removal
- **Finding:** `base.py:render_plan` + overrides in `claude_code.py/opencode.py/pi.py/omp.py` each `from autoconduck.orchestrator.fan_out import build_harness_fan_out_plan` — `fan_out` was deleted in Phase 1, so calling `render_plan` would crash. No live callers (handoff machinery deleted).
- **Grep transcript:** No `render_plan` callers found outside harness class definitions; `fan_out` import appears only inside those four `render_plan` methods plus adapter-internal feature probes. `supports_native_fan_out` flags and config `enable_fan_out`/`fan_out_max_subagents` retained (inert feature flags, not code).
- **Fix:** Remove `render_plan` overrides from all four adapters and base class. Remove the now-dead `from autoconduck.orchestrator.fan_out import ...` line from each. Clean unused `import shutil` from `base.py` only (other adapters still use `shutil.which`). `Any` retained where still used; `shutil` retained in adapters that need it.
- **Files:** `autoconduck/harnesses/base.py`, `autoconduck/harnesses/claude_code.py`, `autoconduck/harnesses/opencode.py`, `autoconduck/harnesses/pi.py`, `autoconduck/harnesses/omp.py`

## Grep Transcripts (acceptance)

```
# record_usage — no real callee, now fail-soft optional
select_closest — 0 hits in autoconduck/** (comment scrubbed, no code refs)
validate_phase_bands — 0 hits
scaled_cost (function name) — 0 hits (scalars max_file_read_scaled_cost retained)
phase_bands — 0 hits (scalars/comments cleaned)
render_plan — 0 hits
fan_out — only inert flags: config.enable_fan_out, fan_out_max_subagents, supports_native_fan_out
record_usage — 0 code hits (isolated via getattr in stats.py)
select_closest — 0 code hits
```

## Pytest Tail

```
270 passed, 4 skipped, 1 warning in 15.45s
# warnings: StarletteDeprecationWarning from fastapi/testclient (pre-existing)
```

## graphify update

Attempted `graphify update .` — no CLI available in this environment (PATH has no `graphify`). Skipped per task order; run manually before commit if desired.

## Decisions & Blockers

- R3 green path: removed both the key and the `planner.py` consumer in same batch (otherwise import error). Alternative defer-to-Batch-2 would leave `phase_bands` key alive but validation dead — rejected as incomplete.
- R1 chose call-site isolation over adding `pricing.record_usage` to keep diff minimal and avoid creating a new pricing contract.
- R5 executor is process-global daemon thread; abandoned ONNX thread on timeout is documented and acceptable per invariant note.
- No blockers. Branch is uncommitted per instructions; new test file `tests/test_phase7c1_batch1.py` covers 7 cases (R1×2, R4, R5×2, R6, R7).
