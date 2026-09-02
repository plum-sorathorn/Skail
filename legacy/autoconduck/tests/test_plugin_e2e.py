"""Phase 4 end-to-end bias flow test — plugin escalate raises next-turn selection floor."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from autoconduck import main as main_mod
from autoconduck import server_streaming
from autoconduck.config.models import Config
from autoconduck.routing.model_pool import CapabilitySLA
from autoconduck.routing.slm_planner import ExecutionPlan, SLMPlanner


@pytest.fixture(autouse=True)
def isolate_home(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOCONDUCK_HOME", str(tmp_path / ".autoconduck"))
    import autoconduck.config.manager as m
    import autoconduck.plugin.ledger as led_mod
    import autoconduck.plugin.bias as bias_mod

    m._config = None
    m._config_digest = None
    m._config_path = None
    m._config_mtime = None
    led_mod.reset_ledger_singleton()
    bias_mod.reset_bias_singleton()
    # reset streaming app so next TestClient picks fresh config
    server_streaming.app = None
    server_streaming._cached.clear()
    main_mod.app = None  # type: ignore
    # also clear bias singleton
    yield
    led_mod.reset_ledger_singleton()
    bias_mod.reset_bias_singleton()
    m._config = None
    server_streaming.app = None
    server_streaming._cached.clear()
    main_mod.app = None  # type: ignore


def _cfg_with_models():
    cfg = Config()
    cfg.plugins.enabled = True
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


def test_plugin_bias_e2e_flow(monkeypatch):
    """Escalate raises floor on next chat completion for that session vs control."""
    import autoconduck.config.manager as m

    cfg = _cfg_with_models()
    m._config = cfg

    # deterministic plan: base floor 0.35 so bias delta is observable
    def fake_plan_sync(self, messages, config=None):
        return ExecutionPlan(
            confidence=0.9,
            task_type="debug",
            complexity_score=7,
            rationale="e2e bias",
            suggested_sla=CapabilitySLA(min_capability_score=0.35, min_context=8000, requires_tools=False),
        )

    monkeypatch.setattr(SLMPlanner, "plan_sync", fake_plan_sync)
    # also ensure _raw_infer not called (plan_sync is mocked, but guard belt)
    monkeypatch.setattr(SLMPlanner, "_raw_infer", lambda self, msgs, config=None: fake_plan_sync(self, msgs, config).model_dump())

    # mock upstream model dispatch — no network (must be async)
    dispatched_kwargs = []

    async def _fake_acompletion(**kw):
        dispatched_kwargs.append(kw)

        class _Resp:
            def model_dump(self):
                return {
                    "id": "chatcmpl-mock",
                    "object": "chat.completion",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "mocked"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
                }

            def __aiter__(self):
                async def _chunks():
                    yield {"id": "chatcmpl-mock", "choices": []}

                return _chunks()

        return _Resp()

    fake_llm = type("FakeLLM", (), {"acompletion": staticmethod(_fake_acompletion)})()
    monkeypatch.setattr(server_streaming, "_litellm", lambda: fake_llm)
    # Pin config so disk reloads do not clobber the in-memory model list
    import autoconduck.config as config_pkg
    import autoconduck.config.manager as mgr_for_patch

    monkeypatch.setattr(mgr_for_patch, "get_config", lambda: cfg)
    monkeypatch.setattr(config_pkg, "get_config", lambda: cfg)
    try:
        import autoconduck.server.server_router as _sr
        import autoconduck.config as _cfg_mod2

        monkeypatch.setattr(_cfg_mod2, "get_config", lambda: cfg)
    except Exception:
        pass
    try:
        import autoconduck.server.server_streaming as _ss2
        # also ensure the already-imported config_module inside server_router sees patched cfg
        import autoconduck.server.server_router as _sr2
        import autoconduck.config as _cm2

        monkeypatch.setattr(_cm2, "get_config", lambda: cfg)
    except Exception:
        pass

    # Build app lazily via main after config is pinned
    main_mod._build()  # type: ignore[attr-defined]
    client = TestClient(main_mod.app)

    session = "omp-session-1"

    # 1. task_start event
    r = client.post("/plugin/events", json={"session_id": session, "task_id": "t1", "kind": "task_start", "data": {"goal": "fix bug"}})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    # 2. escalate
    r2 = client.post("/plugin/escalate", json={"session_id": session, "reason": "consecutive_errors"})
    assert r2.status_code == 200
    j2 = r2.json()
    assert j2["status"] == "ok"
    assert float(j2.get("floor_bump", 0)) > 0

    from autoconduck.plugin.bias import get_bias_store

    assert get_bias_store().get_bump(session) > 0

    from autoconduck.plugin.bias import SessionBiasStore

    observed_bias_lookups = []
    original_get_bump = SessionBiasStore.get_bump

    def _record_get_bump(self, session_id):
        observed_bias_lookups.append(session_id)
        return original_get_bump(self, session_id)

    monkeypatch.setattr(SessionBiasStore, "get_bump", _record_get_bump)

    # Helper to issue chat and capture floor via /stats decisions tail
    def _post_chat(
        session_header: str | None = None,
        payload_session_id: str | None = None,
        stream: bool = False,
    ):
        headers = {}
        if session_header is not None:
            headers["x-autoconduck-session-id"] = session_header
        body = {"model": "autoconduck", "messages": [{"role": "user", "content": "hello from e2e"}], "stream": stream}
        if payload_session_id is not None:
            headers["x-agent-id"] = "omp"
            body["autoconduck_session_id"] = payload_session_id
        resp = client.post("/v1/chat/completions", json=body, headers=headers)
        # should not be 5xx; 200 expected via fake LLM, but at minimum not 500
        assert resp.status_code != 500, resp.text[:500]
        assert resp.status_code == 200, resp.text[:800]
        stats = client.get("/stats")
        assert stats.status_code == 200
        counts = stats.json().get("counts") or []
        # last decision corresponds to this chat (decisions accumulates)
        last = counts[-1] if counts else {}
        return last, stats.json()

    # 3a. control (no session header) — baseline floor
    last_control, _ = _post_chat(None)
    floor_control = float(last_control.get("min_capability_score_applied") or 0.0)

    # 3b. The OMP provider payload marker takes precedence and joins its real session.
    last_biased, stats_biased = _post_chat(
        session_header="header-session-ignored",
        payload_session_id=session,
    )
    floor_biased = float(last_biased.get("min_capability_score_applied") or 0.0)

    # Bias should elevate floor vs control
    assert floor_biased > floor_control, f"biased floor {floor_biased} not > control {floor_control} | control={last_control} biased={last_biased}"
    # Bound check: never above hard cap 0.75
    assert floor_biased <= 0.75
    assert session in observed_bias_lookups
    assert "header-session-ignored" not in observed_bias_lookups
    assert all("autoconduck_session_id" not in kwargs for kwargs in dispatched_kwargs)

    # The private marker is also stripped from the streaming upstream path.
    _post_chat(payload_session_id=session, stream=True)
    assert "autoconduck_session_id" not in dispatched_kwargs[-1]

    # Legacy clients that only provide the header retain the prior identity behavior.
    legacy_session = "legacy-header-session"
    legacy_escalation = client.post(
        "/plugin/escalate",
        json={"session_id": legacy_session, "reason": "consecutive_errors"},
    )
    assert legacy_escalation.status_code == 200
    last_legacy, _ = _post_chat(session_header=legacy_session)
    floor_legacy = float(last_legacy.get("min_capability_score_applied") or 0.0)
    assert floor_legacy > floor_control

    # 4. /stats still 200 and includes the requests (counts grows)
    stats_final = client.get("/stats")
    assert stats_final.status_code == 200
    jfinal = stats_final.json()
    # ensure decisions list has at least our two chats
    assert len(jfinal.get("counts") or []) >= 2
    # ensure usage totals present
    assert "usage" in jfinal

    # Cleanup: bias should still be present (not yet expired; TTL 10, only 1 turn consumed after escalate)
    assert get_bias_store().get_bump(session) > 0
