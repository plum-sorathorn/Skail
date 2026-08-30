# Pre-Transformation Baseline - Two-Plane

**Date:** 2026-08-30
**Branch:** `two-plane`
**Note:** These are pre-transformation baselines recorded on the `two-plane` branch before any source-code modifications (Phase 0).

---

## Pytest - Full Suite

**Command:** `python -m pytest` (pytest `asyncio_mode=auto`; `testpaths = tests`)

**Result:**

```
============================= test session starts =============================
platform win32 -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\Users\plum\Documents\Works\AutoConduck
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.14.1, langsmith-0.10.2, asyncio-1.4.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 288 items

tests\harnesses\test_omp_adapter.py ....                                 [  1%]
tests\integration\test_launcher_process.py ..                            [  2%]
tests\integration\test_simulations.py .......                            [  4%]
tests\test_adversarial_m2.py .............                               [  9%]
tests\test_agent_adapters.py ...........                                 [ 12%]
tests\test_auth_and_providers.py .......                                 [ 15%]
tests\test_cli_and_lifecycle.py ......                                   [ 17%]
tests\test_compat_adversarial.py .....                                   [ 19%]
tests\test_compat_shims.py ...                                           [ 20%]
tests\test_dynamic_factory.py ........                                   [ 22%]
tests\test_e2e_modernization.py .......                                  [ 25%]
tests\test_harness_rendering.py ......                                   [ 27%]
tests\test_launcher.py ................ss.........                       [ 36%]
tests\test_lazy_imports.py ..                                            [ 37%]
tests\test_m2_adversarial_stress.py ...............                      [ 42%]
tests\test_model_pool.py ...................                             [ 49%]
tests\test_omp_integration_flow.py .                                     [ 49%]
tests\test_onboarding_health.py ..                                       [ 50%]
tests\test_orchestrator.py ................                              [ 55%]
tests\test_pricing_and_catalog.py .........                              [ 59%]
tests\test_rag_node.py ..........                                        [ 62%]
tests\test_server_and_apis.py ........                                   [ 65%]
tests\test_session_guard.py ............                                 [ 69%]
tests\test_session_plan.py .....                                         [ 71%]
tests\test_slm_downloader.py .......                                     [ 73%]
tests\test_slm_planner.py .................................              [ 85%]
tests\test_sse_streamer.py .........                                     [ 88%]
tests\test_startup_latency.py .                                          [ 88%]
tests\test_tui_and_onboarding.py .....                                   [ 90%]
tests\test_tui_components.py .....                                       [ 92%]
tests\test_turn_guard.py .......................                         [100%]

============================== warnings summary ===============================
..\..\..\AppData\Local\Python\pythoncore-3.14-64\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\plum\AppData\Local\Python\pythoncore-3.14-64\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================= 286 passed, 2 skipped, 1 warning in 22.03s ==================
```

**Summary:** 288 collected -> **286 passed, 2 skipped, 0 failed**, 1 warning (StarletteDeprecationWarning from `fastapi/testclient.py`).
**Failing tests:** _(none - zero failures)_

Skipped tests (2) are in `tests/test_launcher.py` (`.ss` - platform-conditional skips).

---

## Smoke Test - `scripts/end_to_end_smoke.py`

**Command:** `python scripts/end_to_end_smoke.py`

**Result (verbatim):**

```
C:\Users\plum\AppData\Local\Python\pythoncore-3.14-64\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
  from starlette.testclient import TestClient as TestClient  # noqa
No models are configured in C:\Users\plum\.autoconduck\config.yaml - add a preset or model_list or every request will fall back to a hardcoded default and may fail auth.
mode	requested	response model	status	output
fast	autoconduck	orchestrator-answer (no model field)	502
budget	autoconduck-budget	orchestrator-answer (no model field)	502
expensive	autoconduck-expensive	orchestrator-answer (no model field)	502
slow	autoconduck	orchestrator-answer (no model field)	502
messages	autoconduck	orchestrator-answer (no model field)	502
/v1/models	-	-	200	{"object":"list","data":[{"id":"autoconduck","object":"model","owned_by":"autoco
/stats	-	-	200	{"counts":[{"path":"FAST","route":"fast_direct","tier":"capability_sla","model":
Estimated cost: inspect /stats; this smoke uses at most five tiny model calls plus two local endpoints.
```

**Outcome:** Chat-completion paths (`fast`/`budget`/`expensive`/`slow`/`messages`) returned **502** (`orchestrator-answer (no model field)`) - expected in this environment because no models are configured in `~/.autoconduck/config.yaml` (fallback warning emitted). Local endpoints `/v1/models` and `/stats` returned **200**. No source fix applied per Phase 0 instructions; recorded honestly.

---

## Graph

`graphify update .` completed: `2119 nodes, 4578 edges, 132 communities` - `graph.json`, `graph.html`, `GRAPH_REPORT.md` updated; 1 file produced zero nodes (`pricing_fallback.json` warning).

---

*One-line note: All results above are pre-transformation baselines captured on 2026-08-30 before any proxy/plugin code changes.*

---

## Acceptance Gates (Phase 6)

**Date:** 2026-08-30
**Pre-bump commit:** 8cf64dd
**Branch:** two-plane
**Script:** python scripts/acceptance_gates.py (offline, no models/network)
**Result:** ALL GATES PASS (exit 0)

**Full output (verbatim):**

\C:\Users\plum\AppData\Local\Python\pythoncore-3.14-64\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
  from starlette.testclient import TestClient as TestClient  # noqa
plugin /events ledger error: simulated db I/O failure
Literal API keys in config.yaml are deprecated; use auth.yaml
SLM sync planner error: SLM boom; degrading to fallback.
========================================================================
AutoConduck Phase 6 - Acceptance Gates (offline)
python: 3.14.6  home: C:\Users\plum\AppData\Local\Temp\tmpm38gjz3r\ac_home
========================================================================
GATE 1 hot-path selection (1000 iters, healthy-tool-loop bypass): p50=0.037ms p95=0.060ms max=0.216ms mean=0.043ms - PASS (threshold p95<5ms)
GATE 2 Turn Guard classify() (1000 iters): p50=0.016ms p95=0.023ms max=0.696ms mean=0.014ms - PASS (threshold p95<2ms)
GATE 3 plugin-off parity (same request, plugins off vs on w/o escalation): model off='pricey' on='pricey' floor off=0.3650 on=0.3650 bump=0.0 - PASS
GATE 4 fail-soft matrix: PASS
  4a ledger-broken: /plugin/events 200 (expect <500) chat 200 (expect 200) -> ok
  4b SLM failure fallback: model='cheap' fallback_used=True -> PASS
  4c deprecated keys: loaded=True warned=True logs=['ignoring deprecated config key: ambiguous_high', 'ignoring deprecated config key: ambiguous_low'] -> PASS
  4d fuzz endpoints (13 cases): bad(>=500)=none -> PASS
GATE 5 escalate->bias->floor (session=gate5-sess): control floor=0.3650 biased floor=0.5650 bump=0.2000 elevated=True within_cap<=0.75=True still_present=True control_model='pricey' biased_model='pricey' - PASS
------------------------------------------------------------------------
GATE 1: PASS
GATE 2: PASS
GATE 3: PASS
GATE 4: PASS
GATE 5: PASS
Total wall time: 4217.6ms
========================================================================
ALL GATES PASS
\
**Post-bump version:** 0.5.0 (synced pyproject.toml, autoconduck/__init__.py, npm-packaging/**/package.json, README.md, AGENTS.md)
**Wheels:** npm-packaging/dist/autoconduck-0.5.0-py3-none-any.whl rebuilt and synced to 5 platform python/ dirs; build.py --check clean (5/5 sha256=3a91149aefff)
**Pytest:** 263 passed, 4 skipped, 1 warning (StarletteDeprecationWarning)
**Gate thresholds:** hot-path p95<5ms (0.060ms), Turn Guard p95<2ms (0.023ms) - both PASS with sub-ms typical latency.

