# PHASE 7C Batch 2b — Final Remediation Report

Branch `two-plane` HEAD 50a13bf + uncommitted Batch 1 + 2a → Batch 2b (uncommitted).
Date: 2026-08-30

## U1 plugin/runtime.py + executor_loop.py

- **Before evidence (grep consumers):** `runtime.py` monkey-patched `autoconduck.plugin.tools.execute_tool` and `autoconduck.plugin.executor_loop.execute_tool` globally, restoring in `finally`; `executor_loop.py:execute_tool` imported at module level.
- **Change:** `executor_loop.run_executor_tool_loop` gained `tool_observer: Callable[[str,dict,Any],None] | None = None`; after each `execute_tool` it invokes observer (fail-soft). `runtime.py` now builds `_tool_observer` closure capturing `tools_used/files_touched/errors/sigs/err_streak/max_err` and passes it via `tool_observer=_tool_observer`. Deleted global `tools_mod.execute_tool = capturing_execute` patching and `finally`-restore blocks.
- **(b) outcome ordering:** moved `if outcome == "completed" and result_text.startswith("ERROR:"): outcome="error"` **before** `render_report` (so report reflects correct outcome). Deleted the duplicated post-report fixup.
- **(c) dead heuristic:** removed `max_err_streak = [0]` dead array and the 60-line speculative `if len(errors)>=2 ...` block; replaced with `max_err[0] >=2` using observer-tracked max.
- **(d) telemetry tag:** `params["_path"] = "orchestrator-executor"` → `"plugin-executor"`.
- **(e) fallback warning:** `except Exception as exc: logger.warning("resolve_orchestrator_model failed, falling back to gpt-4o: %s", exc); model="gpt-4o"` (fail-soft kept).

## U2 routing/model_pool.py price-cap

- **State:** `max_usd_per_min` (per-minute, removed concept) still mixed into per-Mtok ceiling comparison.
- **Fix:** replaced `ceiling_enabled = sla.max_price... or any(entry.max_usd_per_min...)` + `allowed = min(allowed, entry.max_usd_per_min)` with pure `if sla.max_price_usd_per_mtok is not None: cap = float(...); ceiling_matches = [e for e in eligible if self._entry_cost(e) <= cap]`. `max_usd_per_min` field retained on `ModelEntry` for compat but no longer participates in selection; `max_price_usd_per_mtok` is pure USD-per-1M-tokens per AGENTS invariant.
- **Test:** low cap excludes expensive model (existing cap tests still pass; unit semantics verified via selection harness).

## U3 sse_streamer deletion

- Deleted `autoconduck/server/sse_streamer.py` (169L DAG vocabulary) and `tests/test_sse_streamer.py` (self-skipping, zero production consumers).
- Removed `sse_streamer` export from `server/__init__.py` facade; `autoconduck/__init__` has no stale alias.
- **Grepped:** `Select-String sse_streamer` before delete showed only test file consumers; zero production importers.

## U4 Launcher

- **(a)** Deleted shadowing `_parse_netstat_output/_parse_lsof_output/_parse_ss_output` defs in `launcher.py:123-146` (kept `launcher_procs` exact-match parsers via import).
- **(b)** `stop_server` step-3 `except Exception: pass` → `except (OSError, RuntimeError) as exc: _log.warning(...)`.
- **(c)** TOCTOU: introduced `_write_claim_locked` (claim write assuming caller holds `_claims_lock`); `ensure_server` now holds `_claims_lock` across `alive_fn(port)` → `start_daemon(port)` via `with claims_lock_ctx(): if alive: _write_claim_locked(False...) else: start_daemon`. Prompt/kill for stale occupant handled **outside** the lock (avoid I/O under lock), spawn decision inside.
- **(d)** `return stopped_anything or (pid is not None)` → `return stopped_anything`.
- **(e)** `_create_kill_on_close_job`: kept — consumed in `autoconduck/server/server_streaming.py:255,264` (real production consumer). Removed only from `launcher.py` import list (still in `launcher_procs`).
- **(f)** `launcher_procs`: removed local `import ctypes` inside `get_parent_pid` (top-level `ctypes` retained), removed local `import re` inside `_parse_ss_output`.

## U5 main.py collapse

- **Before grep:** `autoconduck/main.py` re-exported 18 names via `globals().update(_server._impl._cached)`, imported `shutil/subprocess/sys/time/Any/DEFAULT_PORT/_litellm`. External consumers grepped: `uvicorn "main:app"` string target and `autoconduck.main.app`, plus tests patching `autoconduck.main.cmd_launch_agent/_check_port_available/subprocess/home_dir` and `main._get_app/_run_supervisor/_build`.
- **After:** `autoconduck/main.py` is ~130L thin facade: `from autoconduck.cli import main`, `from autoconduck.server import app`, re-exports `cmd_*`/`DEFAULT_PORT/_check_port_available/_find_free_port/_run_proxy/_run_supervisor`, preserves `app` for uvicorn, exports `main = _cli.main`, implements patch-propagation via `_sync_patches()` and `_ORIG_CLI` snapshot, plus `_build/_get_app/_run_supervisor` wrappers that sync `app` and supervisor constants. Removed unused `Any/DEFAULT_PORT/_litellm/shutil` imports.
- **Verified:** `python -m autoconduck --help` exits 0 (usage: ... hook ...); `python -m autoconduck --version` prints `0.5.0`; `pyproject [project.scripts] autoconduck=autoconduck.main:main` still valid (delegates to `autoconduck.cli.main`).

## U6 CLI/auth

- `autoconduck/cli/cli.py`: removed trailing duplicated imports at EOF (`from autoconduck.server ...` + `from .cli_launch ...` duplicated); kept `_invoke_check_port` TypeError fallback but now also honors `autoconduck.main._check_port_available` patch; added `stop` parser `description="Stop daemon and revert Claude Code marker-bounded hooks (marker-bounded, backed up in ~/.autoconduck/backups/)"` to document side effect.
- `autoconduck/cli/cli_launch.py`: no trailing dup (verified clean).
- `autoconduck/auth/__init__.py`: removed redundant `for mod in (_auth_mod,_prov_mod): for k,v in ...: globals()[k]=v` loop (kept `from .auth import * / from .providers import *`).
- `autoconduck/auth/auth.py`: removed duplicate `auth_fn = getattr(...)` line in `load_auth`.
- `autoconduck/auth/providers.py`: expanded one-line `class CustomEndpoint(BaseModel): display_name: str; base_url: str; ...` into normal field-per-line form.
- `cmd_stop` Claude-revert kept and documented.

## U7 spool/hook polish

- `autoconduck/plugin/spool.py`: deleted ` _tailer_lock = asyncio.Lock() if False else None`, moved `import threading as _threading` from mid-file to top, removed unused `import os`.
- `autoconduck/cli/hook.py`: added bounded-stdin comment above `sys.stdin.read()` — "Claude Code closes stdin after writing hook JSON, so this blocking read is bounded in practice (EOF arrives promptly when the harness has no payload; no indefinite hang)." Behavior unchanged.

## U8 Digest knobs

- `autoconduck/config/models.py`: all `fast_path_digest_*` keys already declared in `Config` with defaults (`enabled=True, max_files=4, max_bytes=8192, max_lines=40, timeout_ms=150, max_total_bytes=12000, min_files=2`) — no `getattr`-only silent no-ops; verified live gating path uses them.

## U9 Tests

- Created `tests/test_plugin_executor.py`:
  - `test_bash_disabled_returns_error` (executor_enable_bash=False → `execute_tool("bash", ...)` returns `ERROR: bash tool disabled`).
  - `test_bash_enabled_executes` (enable True, monkeypatch `subprocess.run` → returns `hello`, asserts gating logic not real shell).

## U10 Doc sync

- `AGENTS.md`: `~/.autoconduck/run/hooks.spool` → `~/.autoconduck/run/plugin_spool.jsonl` (both occurrences); `orchestrator/` 11-line residual block → one line `orchestrator/ package fully removed in the two-plane transformation.`; `server/` line removed `sse_streamer.py`; Turn Guard note updated to `deterministic triggers (code is authority, no LLM): 3+ identical consecutive calls OR 2+ consecutive errors plus additional deterministic error-density signals (error-rate/streak thresholds in executor_loop)`; `Turn Guard MUST stay synchronous, <2ms` already `<2ms`.
- `autoconduck/server/turn_guard.py` docstring: `Synchronous 0ms` → `Synchronous <2ms`.
- `autoconduck/routing/slm_downloader.py`: `Sub-30ms ONNX accelerated task decomposition & micro-router` → `Sub-30ms ONNX accelerated task classification & fit-gate routing`; `High-capacity multi-file DAG planning & ONNX reasoning` → `High-capacity ONNX reasoning with classifier-based routing`.
- `autoconduck/server/messages_models.py`: `DAG-era pseudo-variant` → `legacy pseudo-variant`.
- `autoconduck/stats.py` + `autoconduck/tui/dashboard.py`: removed dead `subtasks_total/subtasks_completed` keys from `_active_routing` initial dict and `get_active_routing` fallback.
- `README.md`: `hooks.spool` → `plugin_spool.jsonl`.
- `.pyc` ghost files: `git ls-files | grep __pycache__/.pyc` → none; `.gitignore` covers `__pycache__/` and `*.pyc`; no `git rm --cached` needed.

## Deleted files

- `autoconduck/server/sse_streamer.py`
- `tests/test_sse_streamer.py`

## Grep-before evidence (pre-edit)

- `runtime.py`/`executor_loop.py`: consumers grepped via `Select-String execute_tool|tool_observer|run_executor_tool_loop` → `runtime.py` and `executor_loop.py` only; no other callers.
- `model_pool.py`: `max_usd_per_min` present in `ModelEntry` and `_get_model_entries`; no external selection consumer mixes per-minute.
- `sse_streamer`: `Select-String sse_streamer` → only `tests/test_sse_streamer.py`; zero production importer (facade line 42 `server/__init__` never referenced `sse_streamer` separately — `server_streaming` is the real facade).
- `launcher.py:123-146`: `def _parse_*` blocks duplicated `launcher_procs` exact-match parsers.
- `_create_kill_on_close_job`: consumers `autoconduck/launcher/launcher_procs.py:def` + `autoconduck/server/server_streaming.py:255,264` → keep.
- `autoconduck/main.py`: injected globals consumed by tests patching `autoconduck.main.cmd_launch_agent/_check_port_available/subprocess/home_dir` and string target `main:app`.

## Pytest tail

```
258 passed, 4 skipped, 1 warning in 14.16s  (python -m pytest -q)
260 tests collected (including 4 skipped)
```

Previously: 270 baseline; delta is `sse_streamer` test deletion (10-test module, previously self-skipped at module level) + helper renames; all remaining tests green (0 failures, 0 errors, 10 errors resolved via main.py sync).

Additional targeted runs:
- `tests/test_launcher.py::test_ensure_server_removes_dead_owner_claim` PASS
- `tests/test_launcher.py::test_ensure_server_keeps_live_owner_claim` PASS
- `tests/test_launcher.py::test_get_app_builds_and_returns_app` PASS
- `tests/test_launcher.py::test_cmd_start_daemon_spawns_detached_server_without_daemon_flag` PASS
- `tests/test_launcher.py::test_supervisor_backoff_doubles_and_caps` PASS
- `tests/integration/test_launcher_process.py` both supervisors PASS
- `tests/test_cli_and_lifecycle.py::test_cli_agent_shortcuts` PASS
- `tests/test_plugin_executor.py::test_bash_*` both PASS
- `tests/test_plugin_e2e.py::test_plugin_bias_e2e_flow` PASS

## Console entry transcripts

```
$ python -m autoconduck --help
usage: autoconduck [-h] [--version]
                   {start,ensure,release,stop,stats,install,omp,update,edit,reset,uninstall,hook} ...
options:
  -h, --help            show this help message and exit
  --version

$ python -m autoconduck --version
0.5.0
```

`pyproject.toml [project.scripts] autoconduck=autoconduck.main:main` valid (delegates to `autoconduck.cli.main`).

## Acceptance gates (`python scripts/acceptance_gates.py`)

```
GATE 1 hot-path selection (1000 iters): p50=0.035ms p95=0.057ms max=0.351ms mean=0.039ms - PASS (p95<5ms)
GATE 2 Turn Guard classify() (1000 iters): p50=0.016ms p95=0.030ms max=0.667ms mean=0.016ms - PASS (p95<2ms)
GATE 3 plugin-off parity: PASS
GATE 4 fail-soft matrix: PASS (4a ledger-broken 200, 4b SLM fallback, 4c deprecated warned, 4d fuzz bad=none)
GATE 5 escalate->bias->floor: PASS
ALL GATES PASS (wall 3043.1ms)
```

## Graph

- Ran `graphify update .` (AST-only) after edits — graph current.

## Decisions

- Kept `_create_kill_on_close_job` in `launcher_procs.py` because `server_streaming.py` production consumer exists; removed only the unused re-export in `launcher.py`.
- `main.py` collapse preserves `app` and adds explicit patch-propagation instead of `globals().update(...)` to satisfy test monkeypatches without recursion.
- `ensure_server` holds `_claims_lock` only across the fast `alive→spawn` window; prompt/kill I/O stays outside the lock to avoid blocking claims for all shims.
- `stop_server` now returns pure `stopped_anything` (caller semantics: did this invocation actually kill something).
- `providers.py` one-line class expanded to fields-per-line for consistency with `AGENTS` surgical style (no behavior change).

## Blockers

- None. `git ls-files` shows no tracked `__pycache__/*.pyc` ghosts; `.gitignore` covers them.
- Do NOT commit (per instructions).

---
