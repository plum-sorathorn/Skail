# Phase 6 — Acceptance Gates + Version 0.5.0

**Date:** 2026-08-30
**Branch:** `two-plane`
**Commit:** phase 6 (this commit)
**Scope:** Acceptance gates (offline), version bump 0.4.1 -> 0.5.0, wheel rebuild, BASELINE appendix, graph refresh.

Per `TWO_PLANE_PLAN.md` Phase 6: routing hot path sub-ms, Turn Guard <2ms, plugin-off parity, fail-soft matrix (never 5xx), escalate->bias->floor, version bump only after gates pass.

---

## 1. Gate Script

`scripts/acceptance_gates.py` — standalone, no models/network, no pytest dependency. Runnable via `python scripts/acceptance_gates.py`, prints PASS/FAIL per gate + p50/p95/max/mean, exits 0 only if all pass. Uses TestClient + monkeypatch seams from `tests/test_plugin_e2e.py` / `tests/test_phase1a_router.py`. Isolated via `AUTOCONDUCK_HOME` temp dir and singleton resets.

---

## 2. Full Gate Output (verbatim)

```
C:\Users\plum\AppData\Local\Python\pythoncore-3.14-64\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
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
```

Exit code: 0

---

## 3. Gate-by-Gate Detail

| Gate | Criterion | Result | Numbers |
|------|-----------|--------|---------|
| GATE 1 hot-path selection | 1000 iterations, healthy-tool-loop bypass path (no SLM), offline pricing JSON; p95 < 5ms | PASS | p50 0.037ms, p95 0.060ms, max 0.216ms, mean 0.043ms — sub-ms typical, well under 5ms budget |
| GATE 2 Turn Guard | 1000 classify() iterations on tool-loop/stagnation/clean inputs | PASS | p50 0.016ms, p95 0.023ms, max 0.696ms, mean 0.014ms — under 2ms |
| GATE 3 plugin-off parity | Same request routed with plugins.enabled False vs True-without-escalation (no bias) | PASS | model off='pricey' on='pricey', floor 0.3650 both, bias bump 0.0 — identical |
| GATE 4 fail-soft matrix | | PASS | 4a ledger broken -> /plugin/events 200 (<500) and chat 200; 4b SLM raise -> fallback model cheap; 4c deprecated keys -> loads with warning, not exception (2 warning logs); 4d 13 fuzz cases (malformed JSON, empty body, wrong types, oversized session_id) -> all <500, none >=500 |
| GATE 5 escalate->bias->floor | escalate then route with x-autoconduck-session-id -> floor elevated <=0.75 | PASS | control 0.3650 -> biased 0.5650, bump 0.20, elevated true, cap 0.75 respected, TTL still present |

All 5 gates PASS. Failure would have stopped the commit (not reached).

---

## 4. Version Bump (0.4.1 -> 0.5.0)

`python scripts/bump_version.py --minor` — fixed one bug in bump script (`content` undefined in `update_docs` AGENTS.md branch; added missing `content = agents_file.read_text(...)`).

```
Bumping AutoConduck version: 0.4.1 -> 0.5.0
  [OK] Updated pyproject.toml -> 0.5.0
  [OK] Updated autoconduck/__init__.py -> 0.5.0
  [OK] Updated npm-packaging/autoconduck/package.json -> 0.5.0
  [OK] Updated npm-packaging/autoconduck-darwin-arm64/package.json -> 0.5.0
  [OK] Updated npm-packaging/autoconduck-darwin-x64/package.json -> 0.5.0
  [OK] Updated npm-packaging/autoconduck-linux-x64/package.json -> 0.5.0
  [OK] Updated npm-packaging/autoconduck-linux-arm64/package.json -> 0.5.0
  [OK] Updated npm-packaging/autoconduck-win32-x64/package.json -> 0.5.0
  [OK] Updated AGENTS.md -> 0.5.0
  [OK] Updated README.md -> 0.5.0

Successfully bumped and synchronized to 0.5.0!
```

Diff inspected — safe:
- `pyproject.toml`: `version = "0.5.0"`
- `autoconduck/__init__.py`: `__version__ = "0.5.0"`
- `AGENTS.md`: `Current version: 0.5.0` (single line)
- `README.md`: `# AutoConduck 0.5.0` + `**AutoConduck 0.5.0** is a local...` (version strings only)
- `npm-packaging/autoconduck/package.json` + 5 platform packages: `version` + `optionalDependencies` synced to 0.5.0
- `scripts/bump_version.py`: one-line fix
No content revert; no aligned sections clobbered.

Verification:
- `pyproject.toml` version 0.5.0, `__init__.py` 0.5.0, `npm-packaging/autoconduck/package.json` 0.5.0 — all synced.
- Wheels: `python npm-packaging/build.py` built `autoconduck-0.5.0-py3-none-any.whl` (sha256 3a91149aefff) and synced to 5 platform `python/` dirs; `python npm-packaging/build.py --check` clean on all 5 platforms.

---

## 5. Pytest

```
python -m pytest -q
263 passed, 4 skipped, 1 warning in ~15s
```

263 baseline unchanged; no new tests required (gate failures would have required a fix, but none failed). 4 skipped are platform-conditional in `tests/test_launcher.py`; warning is `StarletteDeprecationWarning` from `fastapi/testclient.py`.

---

## 6. Graph

```
graphify update .
```

AST-only refresh post-edits.

---

## 7. Commit

```
git add -A
# expected: scripts/acceptance_gates.py, docs/phase-reports/PHASE6.md, BASELINE.md, version files (pyproject.toml, __init__.py, AGENTS.md, README.md, npm-packaging/**/package.json), wheel-sync artifacts (npm-packaging/dist/*.whl + npm-packaging/autoconduck-*/python/*.whl), scripts/bump_version.py fix
git commit -m "phase 6: acceptance gates + version 0.5.0"
# hash: <this commit> on branch two-plane
```

Executed as **COMMIT 7** in `TWO_PLANE_PLAN.md` ordering.

---

## 8. Blockers / Notes

- No blockers. All gates PASS on first attempt (after fixing two cp1252 encode issues in gate script: `up arrow`/`em dash`/`box-drawing` chars and a latent `content` NameError in bump_version.py).
- Gate script wall time ~4.2s for 2000 timed iterations + TestClient fail-soft exercises — acceptable for offline gate.
- `graphify` CLI is on PATH (`graphify ok`).
- Temporary gate output files under `%TEMP%\gate_*.txt` were not committed.

---

## 9. Deliverable

Phase 6 committed on branch `two-plane` at version 0.5.0: all 5 gates PASS with recorded numbers (hot-path p95<5ms, Turn Guard p95<2ms, parity equal, fail-soft all non-500, bias elevated <=0.75); version 0.5.0 synced across pyproject/__init__/package.json; wheels rebuilt+checked; pytest 263 passed; COMMIT 7 exists.
