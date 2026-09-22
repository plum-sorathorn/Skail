#!/usr/bin/env python3
"""Phase 6 acceptance gates - offline, no models/network, no pytest dependency.

GATE 1 hot-path selection 1000x p95<5ms
GATE 2 Turn Guard 1000x p95<2ms
GATE 3 plugin-off parity
GATE 4 fail-soft matrix (a-d)
GATE 5 escalate -> bias -> floor
"""
from __future__ import annotations

import json
import logging
import math
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# -- helpers ----------------------------------------------------------
def percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    k = math.ceil(p / 100 * len(s)) - 1
    k = max(0, min(k, len(s) - 1))
    return s[k]

def fmt_ms(v: float) -> str:
    return f"{v:.3f}ms"

def _cfg_with_models(plugins_enabled: bool = False) -> Any:
    from skail.config.models import Config
    cfg = Config()
    cfg.plugins.enabled = plugins_enabled
    cfg.plugins.escalation_floor_bump = 0.20
    cfg.plugins.escalation_ttl_turns = 10
    cfg.selection.confidence_floor_k = 0.15
    cfg.selection.confidence_floor_max = 0.60
    cfg.model_list = [
        {
            "id": "cheap",
            "provider": "openai",
            "api_key": "k",
            "price_in": 0.1,
            "price_out": 0.1,
            "context_window": 32000,
            "supports_tools": True,
            "capability_score": 0.2,
            "capability_vector": {"reasoning": 0.2, "tool_reliability": 0.3, "code_quality": 0.2, "latency_class": 0.8},
        },
        {
            "id": "pricey",
            "provider": "openai",
            "api_key": "k",
            "price_in": 5.0,
            "price_out": 5.0,
            "context_window": 128000,
            "supports_tools": True,
            "capability_score": 0.9,
            "capability_vector": {"reasoning": 0.9, "tool_reliability": 0.9, "code_quality": 0.9, "latency_class": 0.5},
        },
    ]
    return cfg

def _healthy_tool_loop_messages() -> list[dict]:
    import json as _j
    msgs: list[dict] = [{"role": "user", "content": "Do task"}]
    for i in range(2):
        cid = f"c{i}"
        msgs.extend([
            {"role": "assistant", "tool_calls": [{"id": cid, "type": "function", "function": {"name": "read", "arguments": _j.dumps({"path": f"f{i}.py"})}}]},
            {"role": "tool", "tool_call_id": cid, "name": "read", "content": "ok"},
        ])
    return msgs

def _stagnation_3_identical() -> list[dict]:
    import json as _j
    msgs: list[dict] = [{"role": "user", "content": "Fix bug"}]
    for i in range(3):
        cid = f"c{i}"
        msgs.extend([
            {"role": "assistant", "tool_calls": [{"id": cid, "type": "function", "function": {"name": "read", "arguments": _j.dumps({"path": "a.py"})}}]},
            {"role": "tool", "tool_call_id": cid, "name": "read", "content": "ok"},
        ])
    return msgs

def _consecutive_errors() -> list[dict]:
    import json as _j
    msgs: list[dict] = [{"role": "user", "content": "Fix bug"}]
    for i in range(2):
        cid = f"e{i}"
        msgs.extend([
            {"role": "assistant", "tool_calls": [{"id": cid, "type": "function", "function": {"name": "bash", "arguments": _j.dumps({"command": "pytest"})}}]},
            {"role": "tool", "tool_call_id": cid, "name": "bash", "content": "Error: failed tests"},
        ])
    return msgs

def _clean_user() -> list[dict]:
    return [{"role": "user", "content": "Explain how routing works"}]

def _isolate(tmp_home: Path):
    """Reset singletons for isolation. Must be called after setting SKAIL_HOME."""
    import skail.config.manager as m
    import skail.plugin.ledger as led_mod
    import skail.plugin.bias as bias_mod
    import skail.server.server_streaming as ss
    import skail.main as main_mod
    m._config = None
    m._config_digest = None
    m._config_path = None
    m._config_mtime = None
    try:
        led_mod.reset_ledger_singleton()
    except Exception:
        pass
    try:
        bias_mod.reset_bias_singleton()
    except Exception:
        pass
    ss.app = None
    ss._cached.clear()
    main_mod.app = None

# -- GATE 1 -----------------------------------------------------------
def gate1_hot_path() -> tuple[bool, str]:
    from skail.routing.dispatcher import route
    cfg = _cfg_with_models(False)
    msgs = _healthy_tool_loop_messages()
    # warmup
    route(msgs, config=cfg)
    N = 1000
    times: list[float] = []
    for _ in range(N):
        t0 = time.perf_counter()
        route(msgs, config=cfg)
        times.append((time.perf_counter() - t0) * 1000)
    p50 = percentile(times, 50)
    p95 = percentile(times, 95)
    mx = max(times)
    mean = statistics.mean(times)
    ok = p95 < 5.0
    line = f"GATE 1 hot-path selection ({N} iters, healthy-tool-loop bypass): p50={fmt_ms(p50)} p95={fmt_ms(p95)} max={fmt_ms(mx)} mean={fmt_ms(mean)} - {'PASS' if ok else 'FAIL'} (threshold p95<5ms)"
    return ok, line

# -- GATE 2 -----------------------------------------------------------
def gate2_turn_guard() -> tuple[bool, str]:
    from skail.server.turn_guard import TurnGuard
    guard = TurnGuard()
    inputs = [_healthy_tool_loop_messages(), _stagnation_3_identical(), _consecutive_errors(), _clean_user()]
    # include diverse extra shapes
    extra = [
        [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "Error: permission denied", "is_error": True}]}],
        [{"role": "tool", "tool_call_id": "t1", "name": "grep", "content": "found 12 matches"}],
    ]
    all_inputs = inputs + extra
    guard.classify_turn(all_inputs[0])  # warmup
    N = 1000
    times: list[float] = []
    for i in range(N):
        msgs = all_inputs[i % len(all_inputs)]
        t0 = time.perf_counter()
        guard.classify_turn(msgs)
        times.append((time.perf_counter() - t0) * 1000)
    p50 = percentile(times, 50)
    p95 = percentile(times, 95)
    mx = max(times)
    mean = statistics.mean(times)
    ok = p95 < 2.0
    line = f"GATE 2 Turn Guard classify() ({N} iters): p50={fmt_ms(p50)} p95={fmt_ms(p95)} max={fmt_ms(mx)} mean={fmt_ms(mean)} - {'PASS' if ok else 'FAIL'} (threshold p95<2ms)"
    return ok, line

# -- GATE 3 -----------------------------------------------------------
def gate3_parity() -> tuple[bool, str]:
    from skail.routing.dispatcher import route
    from skail.routing.slm_planner import SLMPlanner, ExecutionPlan
    from skail.routing.model_pool import CapabilitySLA
    from skail.plugin.bias import reset_bias_singleton, get_bias_store

    reset_bias_singleton()
    # Use SLM path (clean user) so bias wiring via _select_planned is exercised
    def fake_plan_sync(self, messages, config=None):
        return ExecutionPlan(
            confidence=0.9,
            task_type="debug",
            complexity_score=5,
            rationale="parity check",
            suggested_sla=CapabilitySLA(min_capability_score=0.35, min_context=8000, requires_tools=False),
        )
    cfg_off = _cfg_with_models(plugins_enabled=False)
    cfg_on = _cfg_with_models(plugins_enabled=True)
    msgs = _clean_user()
    with patch.object(SLMPlanner, "plan_sync", fake_plan_sync):
        with patch.object(SLMPlanner, "_raw_infer", lambda self, m, config=None: fake_plan_sync(self, m, config).model_dump()):
            dec_off = route(msgs, config=cfg_off, session_id="sess-parity")
            dec_on = route(msgs, config=cfg_on, session_id="sess-parity")
    # Compare
    model_equal = dec_off.model == dec_on.model
    floor_off = float(getattr(dec_off, "min_capability_score_applied", 0.0) or 0.0)
    floor_on = float(getattr(dec_on, "min_capability_score_applied", 0.0) or 0.0)
    floor_equal = abs(floor_off - floor_on) < 1e-9
    # also ensure bias store not engaged without escalation
    bump = get_bias_store().get_bump("sess-parity")
    bias_zero = bump == 0.0
    ok = model_equal and floor_equal and bias_zero
    detail = f"model off={dec_off.model!r} on={dec_on.model!r} floor off={floor_off:.4f} on={floor_on:.4f} bump={bump}"
    line = f"GATE 3 plugin-off parity (same request, plugins off vs on w/o escalation): {detail} - {'PASS' if ok else 'FAIL'}"
    reset_bias_singleton()
    return ok, line

# -- GATE 4 -----------------------------------------------------------
def gate4_fail_soft(tmp_home: Path) -> tuple[bool, str]:
    sub_results: list[str] = []
    all_ok = True

    # --- 4a ledger I/O broken -> /plugin/events non-5xx and chat route still succeeds
    gate4a_ok = False
    gate4a_detail = ""
    try:
        import skail.config.manager as m
        import skail.main as main_mod
        import skail.server.server_streaming as ss
        import skail.plugin.ledger as led_mod
        import skail.plugin.bias as bias_mod
        from fastapi.testclient import TestClient
        from skail.routing.slm_planner import SLMPlanner, ExecutionPlan
        from skail.routing.model_pool import CapabilitySLA

        _isolate(tmp_home)
        cfg = _cfg_with_models(plugins_enabled=True)
        m._config = cfg
        # patch get_config to return our cfg even after disk reload attempts
        import skail.config as config_pkg
        import skail.config.manager as mgr_for_patch
        orig_get_cfg = mgr_for_patch.get_config
        orig_pkg_get_cfg = config_pkg.get_config
        mgr_for_patch.get_config = lambda: cfg  # type: ignore
        config_pkg.get_config = lambda: cfg  # type: ignore
        try:
            import skail.server.server_router as _sr
            import skail.config as _cfg2
            _cfg2.get_config = lambda: cfg  # type: ignore
        except Exception:
            pass
        # deterministic plan + fake litellm
        def fake_plan_sync(self, messages, config=None):
            return ExecutionPlan(confidence=0.9, task_type="debug", complexity_score=5, rationale="4a", suggested_sla=CapabilitySLA(min_capability_score=0.35, min_context=8000, requires_tools=False))
        orig_plan = SLMPlanner.plan_sync
        SLMPlanner.plan_sync = fake_plan_sync  # type: ignore

        async def _fake_acompletion(**kw):
            class _Resp:
                def model_dump(self):
                    return {"id": "chatcmpl-mock", "object": "chat.completion", "choices": [{"index": 0, "message": {"role": "assistant", "content": "mocked"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}}
            return _Resp()
        fake_llm = type("FakeLLM", (), {"acompletion": staticmethod(_fake_acompletion)})()
        orig_litellm = ss._litellm if hasattr(ss, "_litellm") else None
        ss._litellm = lambda: fake_llm  # type: ignore

        # build app
        main_mod._build()  # type: ignore
        client = TestClient(main_mod.app, raise_server_exceptions=False)

        # break ledger: patch get_ledger to return an object that raises on enqueue
        orig_get_ledger = led_mod.get_ledger
        class BrokenLedger:
            def enqueue(self, *a, **kw):
                raise OSError("simulated db I/O failure")
            def count_in_memory(self, *a, **kw):
                raise OSError("simulated db I/O failure")
            def query_events(self, *a, **kw):
                raise OSError("simulated")
            def get_counts(self, *a, **kw):
                raise OSError("simulated")
        led_mod.get_ledger = lambda: BrokenLedger()  # type: ignore
        # also break via bias store? not needed

        r_events = client.post("/plugin/events", json={"session_id": "sess-4a", "task_id": "t1", "kind": "task_start", "data": {"goal": "x"}})
        # should be non-5xx (handler is fail-soft -> returns 200 ignored/ok)
        events_ok = r_events.status_code < 500
        # chat route still succeeds (200 via fake LLM)
        r_chat = client.post("/v1/chat/completions", json={"model": "skail", "messages": [{"role": "user", "content": "hello"}], "stream": False}, headers={"x-skail-session-id": "sess-4a"})
        chat_ok = r_chat.status_code < 500 and r_chat.status_code == 200
        gate4a_ok = events_ok and chat_ok
        gate4a_detail = f"4a ledger-broken: /plugin/events {r_events.status_code} (expect <500) chat {r_chat.status_code} (expect 200) -> {'ok' if gate4a_ok else 'FAIL'}"
        # restore
        led_mod.get_ledger = orig_get_ledger  # type: ignore
        if orig_litellm is not None:
            ss._litellm = orig_litellm  # type: ignore
        SLMPlanner.plan_sync = orig_plan  # type: ignore
        mgr_for_patch.get_config = orig_get_cfg  # type: ignore
        config_pkg.get_config = orig_pkg_get_cfg  # type: ignore
        try:
            import skail.config as _cfg3
            _cfg3.get_config = orig_pkg_get_cfg  # type: ignore
        except Exception:
            pass
        _isolate(tmp_home)
    except Exception as exc:
        gate4a_detail = f"4a ledger-broken: exception {exc!r} -> FAIL"
        gate4a_ok = False
        try:
            import skail.plugin.ledger as _lm2
            import skail.config.manager as _mm2
            _mm2._config = None
            _lm2.reset_ledger_singleton()
        except Exception:
            pass
    sub_results.append(gate4a_detail)
    all_ok = all_ok and gate4a_ok

    # --- 4b SLM plan_sync raising -> fallback selection returns a model
    gate4b_ok = False
    gate4b_detail = ""
    try:
        from skail.routing.dispatcher import route
        from skail.routing.slm_planner import SLMPlanner
        cfg = _cfg_with_models(False)
        def failing_raw(self, messages, config=None):
            raise RuntimeError("SLM boom")
        with patch.object(SLMPlanner, "_raw_infer", failing_raw):
            dec = route(_clean_user(), config=cfg)
        gate4b_ok = dec.model is not None
        gate4b_detail = f"4b SLM failure fallback: model={dec.model!r} fallback_used={getattr(dec.plan, 'fallback_used', '?')} -> {'PASS' if gate4b_ok else 'FAIL'}"
    except Exception as exc:
        gate4b_detail = f"4b SLM failure fallback: exception {exc!r} -> FAIL"
        gate4b_ok = False
    sub_results.append(gate4b_detail)
    all_ok = all_ok and gate4b_ok

    # --- 4c config yaml containing removed keys -> loads with warning, not exception
    gate4c_ok = False
    gate4c_detail = ""
    try:
        import yaml
        import skail.config.manager as mgr
        import logging
        # write temp config file with deprecated keys
        cfg_path = tmp_home / ".skail" / "config.yaml"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        raw_yaml = {
            "port": 11434,
            "ambiguous_low": 0.6,
            "ambiguous_high": 0.75,
            "escalation_threshold": 0.8,
            "selection": {
                "slow_threshold": 0.75,
                "min_orchestrator_complexity": 0.72,
                "deescalation_threshold": 0.4,
            },
        }
        cfg_path.write_text(yaml.safe_dump(raw_yaml), encoding="utf-8")
        # capture warnings
        logs: list[str] = []
        handler = logging.Handler()
        handler.emit = lambda rec: logs.append(rec.getMessage())  # type: ignore
        logger = logging.getLogger("skail")
        prev_level = logger.level
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)
        try:
            cfg_loaded = mgr.load_config(path=cfg_path)
            # should not raise and should have ignored keys (config has no attr ambiguous_low)
            has_no_deprecated = not hasattr(cfg_loaded, "ambiguous_low")
            warned = any("ignoring deprecated config key" in m for m in logs)
            gate4c_ok = cfg_loaded is not None and warned
            gate4c_detail = f"4c deprecated keys: loaded={cfg_loaded is not None} warned={warned} logs={logs[:2]} -> {'PASS' if gate4c_ok else 'FAIL'}"
        finally:
            logger.removeHandler(handler)
            logger.setLevel(prev_level)
    except Exception as exc:
        gate4c_detail = f"4c deprecated keys: exception {exc!r} -> FAIL"
        gate4c_ok = False
    sub_results.append(gate4c_detail)
    all_ok = all_ok and gate4c_ok

    # --- 4d plugin endpoints fuzz: malformed JSON, empty body, wrong types, oversized session_id
    gate4d_ok = False
    gate4d_detail = ""
    try:
        import skail.config.manager as m
        import skail.main as main_mod
        import skail.server.server_streaming as ss
        import skail.plugin.ledger as led_mod
        import skail.plugin.bias as bias_mod
        from fastapi.testclient import TestClient

        _isolate(tmp_home)
        cfg = _cfg_with_models(plugins_enabled=True)
        m._config = cfg
        import skail.config as config_pkg
        import skail.config.manager as mgr_for_patch
        orig_get_cfg = mgr_for_patch.get_config
        orig_pkg_get_cfg = config_pkg.get_config
        mgr_for_patch.get_config = lambda: cfg  # type: ignore
        config_pkg.get_config = lambda: cfg  # type: ignore
        try:
            main_mod._build()  # type: ignore
        except Exception:
            pass
        client = TestClient(main_mod.app, raise_server_exceptions=False)
        fuzz_cases: list[tuple[str, str, int]] = []
        huge_sid = "x" * 20000

        def _check(resp, label):
            fuzz_cases.append((label, str(resp.status_code), resp.status_code))

        # malformed JSON bodies (raw)
        _check(client.post("/plugin/events", content=b"{not json", headers={"Content-Type": "application/json"}), "events malformed json")
        _check(client.post("/plugin/escalate", content=b"{not json", headers={"Content-Type": "application/json"}), "escalate malformed json")
        _check(client.post("/plugin/execute", content=b"{not json", headers={"Content-Type": "application/json"}), "execute malformed json")
        # empty bodies
        _check(client.post("/plugin/events", content=b"", headers={"Content-Type": "application/json"}), "events empty body")
        _check(client.post("/plugin/escalate", content=b"", headers={"Content-Type": "application/json"}), "escalate empty body")
        # wrong types
        _check(client.post("/plugin/events", json={"session_id": 12345, "task_id": 999, "kind": 123, "data": "not-a-dict"}), "events wrong types")
        _check(client.post("/plugin/escalate", json={"session_id": 123, "reason": 999}), "escalate wrong types")
        _check(client.post("/plugin/escalate", json={"session_id": "", "reason": "consecutive_errors"}), "escalate empty session")
        # oversized session_id
        _check(client.post("/plugin/events", json={"session_id": huge_sid, "task_id": "t1", "kind": "task_start", "data": {}}), "events huge sid")
        _check(client.post("/plugin/escalate", json={"session_id": huge_sid, "reason": "consecutive_errors"}), "escalate huge sid")
        _check(client.get(f"/plugin/contract?session={huge_sid}"), "contract huge sid")
        _check(client.post("/plugin/execute", json={"session_id": huge_sid, "goal": "do thing"}), "execute huge sid")
        # also GET contract no session
        _check(client.get("/plugin/contract"), "contract no session")

        bad = [(label, code) for label, code, sc in fuzz_cases if sc >= 500]
        gate4d_ok = len(bad) == 0
        gate4d_detail = f"4d fuzz endpoints ({len(fuzz_cases)} cases): bad(>=500)={bad if bad else 'none'} -> {'PASS' if gate4d_ok else 'FAIL'}"
        # restore
        mgr_for_patch.get_config = orig_get_cfg  # type: ignore
        config_pkg.get_config = orig_pkg_get_cfg  # type: ignore
        _isolate(tmp_home)
    except Exception as exc:
        gate4d_detail = f"4d fuzz endpoints: exception {exc!r} -> FAIL"
        gate4d_ok = False
    sub_results.append(gate4d_detail)
    all_ok = all_ok and gate4d_ok

    line = f"GATE 4 fail-soft matrix: {'PASS' if all_ok else 'FAIL'}\n  " + "\n  ".join(sub_results)
    return all_ok, line

# -- GATE 5 -----------------------------------------------------------
def gate5_bias(tmp_home: Path) -> tuple[bool, str]:
    from skail.routing.dispatcher import route
    from skail.routing.slm_planner import SLMPlanner, ExecutionPlan
    from skail.routing.model_pool import CapabilitySLA
    from skail.plugin.bias import reset_bias_singleton, get_bias_store

    reset_bias_singleton()
    def fake_plan_sync(self, messages, config=None):
        return ExecutionPlan(
            confidence=0.9,
            task_type="debug",
            complexity_score=7,
            rationale="gate5",
            suggested_sla=CapabilitySLA(min_capability_score=0.35, min_context=8000, requires_tools=False),
        )
    cfg = _cfg_with_models(plugins_enabled=True)
    cfg.plugins.escalation_floor_bump = 0.20
    cfg.plugins.escalation_ttl_turns = 10
    session = "gate5-sess"

    with patch.object(SLMPlanner, "plan_sync", fake_plan_sync):
        with patch.object(SLMPlanner, "_raw_infer", lambda self, m, config=None: fake_plan_sync(self, m, config).model_dump()):
            # control: no session
            dec_control = route(_clean_user(), config=cfg, session_id=None)
            floor_control = float(getattr(dec_control, "min_capability_score_applied", 0.0) or 0.0)
            # escalate
            store = get_bias_store()
            store.apply_escalation(session, cfg.plugins.escalation_floor_bump, cfg.plugins.escalation_ttl_turns)
            bump = store.get_bump(session)
            # biased: with session header (but dispatcher will increment_turn in server_router; here we just pass session_id)
            # Simulate per-turn increment: route does NOT increment turn - server_router does. So manually we keep store as-is.
            # Bias should be applied via _select_planned reading get_bump(session)
            dec_biased = route(_clean_user(), config=cfg, session_id=session)
            floor_biased = float(getattr(dec_biased, "min_capability_score_applied", 0.0) or 0.0)

    elevated = floor_biased > floor_control
    within_cap = floor_biased <= 0.75 + 1e-9
    # also check TTL not expired after 1 turn (bias still present)
    still_present = get_bias_store().get_bump(session) > 0
    ok = elevated and within_cap
    detail = f"control floor={floor_control:.4f} biased floor={floor_biased:.4f} bump={bump:.4f} elevated={elevated} within_cap<={0.75}={within_cap} still_present={still_present} control_model={dec_control.model!r} biased_model={dec_biased.model!r}"
    line = f"GATE 5 escalate->bias->floor (session={session}): {detail} - {'PASS' if ok else 'FAIL'}"
    reset_bias_singleton()
    return ok, line

# -- main -------------------------------------------------------------
def main() -> int:
    start_all = time.perf_counter()
    # use a temp HOME to keep ledger/bias isolated and not pollute real user dir
    with tempfile.TemporaryDirectory() as td:
        tmp_home = Path(td) / "ac_home"
        tmp_home.mkdir(parents=True, exist_ok=True)
        orig_home = os.environ.get("SKAIL_HOME")
        os.environ["SKAIL_HOME"] = str(tmp_home)
        # also reset singletons to pick up new home
        try:
            _isolate(tmp_home)
        except Exception:
            pass
        print("=" * 72)
        print("Skail Phase 6 - Acceptance Gates (offline)")
        print(f"python: {sys.version.split()[0]}  home: {tmp_home}")
        print("=" * 72)
        results: list[tuple[str, bool, str]] = []
        # Gate ordering: 1,2 independent; 3,5 need clean state; 4 is heavy
        for name, fn in [
            ("GATE 1", gate1_hot_path),
            ("GATE 2", gate2_turn_guard),
            ("GATE 3", gate3_parity),
        ]:
            try:
                ok, line = fn()
            except Exception as exc:
                ok, line = False, f"{name} EXCEPTION: {exc!r}"
                import traceback as _tb
                line += "\n" + _tb.format_exc()
            print(line)
            results.append((name, ok, line))
        # Gate 4 needs tmp_home
        try:
            ok, line = gate4_fail_soft(tmp_home)
        except Exception as exc:
            import traceback as _tb
            ok, line = False, f"GATE 4 EXCEPTION: {exc!r}\n" + _tb.format_exc()
        print(line)
        results.append(("GATE 4", ok, line))
        # Gate 5
        try:
            ok, line = gate5_bias(tmp_home)
        except Exception as exc:
            import traceback as _tb
            ok, line = False, f"GATE 5 EXCEPTION: {exc!r}\n" + _tb.format_exc()
        print(line)
        results.append(("GATE 5", ok, line))

        elapsed = (time.perf_counter() - start_all) * 1000
        print("-" * 72)
        all_pass = all(ok for _, ok, _ in results)
        for name, ok, _ in results:
            print(f"{name}: {'PASS' if ok else 'FAIL'}")
        print(f"Total wall time: {elapsed:.1f}ms")
        print("=" * 72)
        if all_pass:
            print("ALL GATES PASS")
        else:
            print("GATES FAILED - see details above")
        # restore env
        if orig_home is None:
            os.environ.pop("SKAIL_HOME", None)
        else:
            os.environ["SKAIL_HOME"] = orig_home
        try:
            _isolate(Path(tmp_home))
        except Exception:
            pass
        return 0 if all_pass else 1

if __name__ == "__main__":
    raise SystemExit(main())
