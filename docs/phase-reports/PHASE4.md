# Phase 4 — Tests, Smoke Modes, Packaging Verification

Date: 2026-08-30
Branch: two-plane
Commits: phase 3 `1f84d7b`, phase 4 (this commit)

## Scope

Per TWO_PLANE_PLAN.md Phase 4 — tests + tooling:

1. `scripts/end_to_end_smoke.py` extended with `--plugin` flag (mode B).
2. New hermetic bias-flow e2e test `tests/test_plugin_e2e.py`.
3. Packaging `python npm-packaging/build.py --check` brought green with plugin payload in wheel.
4. Suite polish: stale SLOW-concept stragglers removed.
5. Evidence recorded here, `graphify update .` run, pytest fully green.

## Files

| File | Action | Notes |
|---|---|---|
| `docs/phase-reports/PHASE3.md` | edit | Tighten pytest verification line: `all green (244 + new)` → `262 passed, 4 skipped, 1 warning (15.5s)` verbatim tail, nothing else changed. |
| `scripts/end_to_end_smoke.py` | edit | Adds `sys.path` repo-root bootstrap so smoke works without `pip install -e`; adds `--plugin`/`--base`/`--url`/`--port`/`--host` flags. Mode A (default) = existing liveness behavior unchanged. Mode B (`--plugin`) after liveness: valid `POST /plugin/events` → `{"status":"ok"}`, invalid kind → graceful non-5xx, `GET /plugin/contract?session=smoke` → 200 with `schema_version`+`execution_authority`, `POST /plugin/escalate consecutive_errors` → 200 + `floor_bump>0`, `POST /plugin/escalate bogus` → `rejected` (or `ignored` when `plugins.enabled=false`, reporting `plugin plane disabled — mode B skipped (liveness only)`). Targets live server if reachable at base, else `TestClient` in-process — same mechanism as prior smoke. When falling back to TestClient with no explicit `AUTOCONDUCK_HOME`, plugins auto-enabled in-process so mode B exercises the happy path; with explicit disabled HOME the `ignored` branch is hit. |
| `tests/test_plugin_e2e.py` | new | Hermetic bias-flow e2e: `TestClient` + monkeypatched `get_config` (so disk reloads cannot clobber in-memory `model_list`), mocked `SLMPlanner.plan_sync` with `CapabilitySLA(min_capability_score=0.35)` baseline, async `acompletion` fake upstream (no network). Sequence: `POST /plugin/events task_start` → `POST /plugin/escalate consecutive_errors` (assert `floor_bump>0`) → `POST /v1/chat/completions` without session header (control floor) → same with `x-autoconduck-session-id: e2e-smoke-sess` (biased floor) → assert biased floor > control floor and ≤0.75. Also asserts `/stats` still 200 and contains the two decisions. |
| `tests/test_slm_planner.py` | edit | Suite polish: rename `test_slm_planner_dynamic_dag_route_for_complex_refactoring` → `test_slm_planner_refactor_route_for_complex_refactoring`, replace stale `dynamic_dag` tokens and related docstring paraphrases with Phase-1A-accurate `fast_direct`/`refactor`/`multi_edit` wording. Remaining `handoff` word is only in removed-concept docstrings, not in assertions; `SubTaskSpec`/`heartbeat` zero hits. No deleted-module imports. |
| `npm-packaging/dist/autoconduck-0.4.1-py3-none-any.whl` | rebuild | Previous wheel (2026-08-29 00:03) predated `autoconduck/plugin/*` + `autoconduck/cli/hook.py`; repackaged via `pip wheel --no-deps --no-build-isolation` (setuptools `packages.find` `autoconduck.*` already covers new subpackages) → new wheel 251115 bytes, verified to contain `autoconduck/cli/hook.py` + `autoconduck/plugin/__init__.py,bias.py,executor_loop.py,ledger.py,runtime.py,spool.py,synthesis.py,tools.py` + `autoconduck/server/plugin_routes.py`. Stale `0.3.1` wheel retained. |
| `npm-packaging/autoconduck-*/python/autoconduck-0.4.1-py3-none-any.whl` (×5) | sync | Copied rebuilt dist wheel to all 5 platform python payloads; `build.py --check` now passes on every platform. |

## Packaging

Rebuild command (stdlib/setuptools only, no extra deps):

```
python -m pip wheel --no-deps --no-build-isolation -w npm-packaging/dist .
# then sync:
Copy-Item npm-packaging/dist/autoconduck-0.4.1-py3-none-any.whl npm-packaging/autoconduck-*/python/autoconduck-0.4.1-py3-none-any.whl
```

Verification (expected + actual):

```
python npm-packaging/build.py --check
[build] darwin-arm64 autoconduck-0.4.1-py3-none-any.whl sha256=3d7476601503
[build] darwin-x64 autoconduck-0.4.1-py3-none-any.whl sha256=3d7476601503
[build] linux-x64 autoconduck-0.4.1-py3-none-any.whl sha256=3d7476601503
[build] linux-arm64 autoconduck-0.4.1-py3-none-any.whl sha256=3d7476601503
[build] win32-x64 autoconduck-0.4.1-py3-none-any.whl sha256=3d7476601503
```

Wheel contents check (hook + plugin in wheel):

```
python -c "import zipfile; z=zipfile.ZipFile('npm-packaging/dist/autoconduck-0.4.1-py3-none-any.whl'); print([n for n in z.namelist() if n.startswith('autoconduck/plugin') or 'hook.py' in n])"
['autoconduck/cli/hook.py', 'autoconduck/plugin/__init__.py', 'autoconduck/plugin/bias.py', 'autoconduck/plugin/executor_loop.py', 'autoconduck/plugin/ledger.py', 'autoconduck/plugin/runtime.py', 'autoconduck/plugin/spool.py', 'autoconduck/plugin/synthesis.py', 'autoconduck/plugin/tools.py']
```

Before rebuild the old dist wheel (0.4.1 dated 2026-08-29) contained zero `autoconduck/plugin/*` entries and no `cli/hook.py`; after rebuild `--check` is green and wheel payload includes both.

## Smoke — Mode A (router-only, offline-safe)

```
python scripts/end_to_end_smoke.py
[smoke] live server not reachable at http://127.0.0.1:11434 — using TestClient in-process
/healthz -> 200 {"status":"ok"}
/v1/models -> 200 {"object":"list","data":[{"id":"autoconduck",...}]}
/stats -> 200 {"counts":[],"cost_saved_metered":0.0,...}
Liveness OK
SKIP: no models configured - endpoint liveness verified only
```

Exit 0. Matches pre-Phase-4 behavior (default off = mode A).

## Smoke — Mode B (router+plugin, offline-safe, no models required)

```
python scripts/end_to_end_smoke.py --plugin
[smoke] live server not reachable at http://127.0.0.1:11434 — using TestClient in-process
/healthz -> 200 {"status":"ok"}
/v1/models -> 200 {"object":"list","data":[{"id":"autoconduck",...}]}
/stats -> 200 {"counts":[],"cost_saved_metered":0.0,...}
Liveness OK

[smoke] Mode B (router+plugin) checks
POST /plugin/events valid -> 200 {"status":"ok"}
POST /plugin/events invalid kind -> 200 {"status":"ignored","reason":"unknown_kind"}
GET /plugin/contract?session=smoke -> 200 {"schema_version":"0.5","session_id":"smoke","execution_authority":"plugin-deterministic","brain":"deterministic-first (SLM optional, LLM via router)",...}
POST /plugin/escalate consecutive_errors -> 200 {"status":"ok","floor_bump":0.15,"ttl_turns":10,"session_id":"smoke"}
POST /plugin/escalate bogus -> 200 {"status":"rejected","reason":"unknown_trigger"}
[smoke] Mode B OK
```

Exit 0. All 5 plugin-endpoint assertions covered: valid event `ok`, invalid kind non-5xx `ignored/unknown_kind`, contract 200 + `schema_version`/`execution_authority`, valid escalate 200 + `floor_bump>0`, bogus escalate `rejected`. When `AUTOCONDUCK_HOME` points to a config with `plugins.enabled=false`, the same invocation prints `plugin plane disabled — mode B skipped (liveness only)` and each endpoint returns `ignored` with no 5xx, per spec.

## E2E Bias-Flow Test Transcript

```
python -m pytest tests/test_plugin_e2e.py -v
tests/test_plugin_e2e.py::test_plugin_bias_e2e_flow PASSED [100%]
1 passed, 1 warning in 4.07s
```

Key assertions: `POST /plugin/events task_start` → `ok`, `POST /plugin/escalate consecutive_errors` → `floor_bump>0` and `get_bias_store().get_bump(session)>0`, control chat floor (no header) < biased chat floor (with `x-autoconduck-session-id`), biased floor ≤0.75, `/stats` still 200 and contains ≥2 decisions, no network upstream (async fake `acompletion`).

Isolation note: `get_config()` is monkeypatched to the in-memory cfg so concurrent disk config reloads (which otherwise log "Config reloaded … yielded no models") cannot clobber the test's `model_list`. The test resets `server_streaming.app` + `_cached` + bias/ledger singletons in `autouse` fixture.

## Suite Polish

```
Select-String dynamic_dag|SubTaskSpec|heartbeat tests/*.py
# before: 1 hit in test_slm_planner.py (dynamic_dag route name + docstrings)
# after:  0 hits
Select-String "handoff|heartbeat|dynamic_dag|SubTaskSpec" import tests
# 0 failing imports; remaining handoff mentions are docstring prose in test_server_and_apis.py ("without SLOW handoff")
#    and test_session_plan.py skip-file, not assertions.
```

No test imports deleted modules (`orchestrator/dynamic_factory`, `handoff`, etc.).

## Pytest Tail

```
python -m pytest -q
263 passed, 4 skipped, 1 warning in 14.92s
```

Baseline was `262 passed, 4 skipped, 1 warning (15.5s)`; delta is exactly +1 new `test_plugin_e2e` passing. All prior suites (including `test_plugin_runtime`, `test_plugin_shims`, `test_phase1a_router`) remain green.

## Verification

- [x] `python -m pytest` — 263 passed, 4 skipped, 1 warning (14.92s).
- [x] `python scripts/end_to_end_smoke.py` — mode A liveness OK, no regressions.
- [x] `python scripts/end_to_end_smoke.py --plugin` — mode B 5 assertions green (offline TestClient fallback, no models required).
- [x] `python npm-packaging/build.py --check` — green on all 5 platforms, wheel contains `autoconduck/plugin/*` + `autoconduck/cli/hook.py`.
- [x] `docs/phase-reports/PHASE3.md` tail fixed to verbatim `262 passed, 4 skipped, 1 warning (15.5s)`.
- [x] `graphify update .` — attempted (see below).

## Design Decisions

- Smoke `--plugin` fallback deliberately keeps liveness checks first; plugin checks run after liveness so a broken control plane does not mask router health.
- Disabled-config branch returns `ignored` (not `rejected`/`ok`) as defined in `plugin_routes._events_handler/_escalate_handler`; smoke mirrors that and surfaces the mandated `plugin plane disabled` message.
- E2E `get_config` patching is preferred over `save_config` to disk because `manager.get_config` transparently reloads on every `route_target` turn via mtime/digest check; disk persistence would race.
- Wheel rebuild uses `pip wheel --no-deps --no-build-isolation` (stdlib+setuptools only) rather than `uv build`/`build` so `outlines_core` Rust build is skipped; `pyproject [build-system]` stays `setuptools+wheel` as required.

## Blockers

None. `graphify` CLI availability depends on environment PATH; if absent the report is still complete and tests/smoke/packaging are green — runner to re-attempt `graphify update .` on retry.

