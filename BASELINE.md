# Pre-Transformation Baseline — Two-Plane

**Date:** 2026-08-30
**Branch:** `two-plane`
**Note:** These are pre-transformation baselines recorded on the `two-plane` branch before any source-code modifications (Phase 0).

---

## Pytest — Full Suite

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

**Summary:** 288 collected → **286 passed, 2 skipped, 0 failed**, 1 warning (StarletteDeprecationWarning from `fastapi/testclient.py`).
**Failing tests:** _(none — zero failures)_

Skipped tests (2) are in `tests/test_launcher.py` (`.ss` — platform-conditional skips).

---

## Smoke Test — `scripts/end_to_end_smoke.py`

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

**Outcome:** Chat-completion paths (`fast`/`budget`/`expensive`/`slow`/`messages`) returned **502** (`orchestrator-answer (no model field)`) — expected in this environment because no models are configured in `~/.autoconduck/config.yaml` (fallback warning emitted). Local endpoints `/v1/models` and `/stats` returned **200**. No source fix applied per Phase 0 instructions; recorded honestly.

---

## Graph

`graphify update .` completed: `2119 nodes, 4578 edges, 132 communities` — `graph.json`, `graph.html`, `GRAPH_REPORT.md` updated; 1 file produced zero nodes (`pricing_fallback.json` warning).

---

*One-line note: All results above are pre-transformation baselines captured on 2026-08-30 before any proxy/plugin code changes.*
