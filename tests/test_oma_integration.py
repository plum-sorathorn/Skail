"""Integration tests for OMA proxy routing plane: complexity gating, recursion protection, and fail-soft handling."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient

from autoconduck import server_streaming
from autoconduck.config.models import Config
from autoconduck.routing.slm_planner import SLMPlanner
from autoconduck.server.server_router import route_target


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
    server_streaming.app = None
    server_streaming._cached.clear()
    yield
    led_mod.reset_ledger_singleton()
    bias_mod.reset_bias_singleton()
    m._config = None
    server_streaming.app = None
    server_streaming._cached.clear()


def _cfg_with_oma():
    cfg = Config()
    cfg.plugins.enabled = True
    cfg.plugins.oma_enabled = True
    cfg.plugins.execute_enabled = True
    cfg.model_list = [
        {
            "id": "cheap",
            "provider": "openai",
            "api_key": "k",
            "price_in": 0.1,
            "price_out": 0.1,
            "context_window": 32000,
            "supports_tools": True,
            "capability_score": 0.5,
        }
    ]
    return cfg


class DummyRequest:
    def __init__(self, headers: dict[str, str] | None = None):
        self.headers = headers or {}


@pytest.mark.asyncio
async def test_high_complexity_triggers_oma(monkeypatch):
    """High complexity prompt with plugins.enabled=True triggers OMA delegation."""
    import autoconduck.config.manager as m

    cfg = _cfg_with_oma()
    m._config = cfg

    mock_start_task = AsyncMock(
        return_value={
            "task_id": "t123",
            "session_id": "s123",
            "status": "ok",
            "runner_started": True,
            "report": "Refactoring completed by OMA subagents",
            "mode": "auto",
            "tasks": [],
            "elapsed_s": 1.2,
        }
    )

    monkeypatch.setattr("autoconduck.plugin.runtime.start_task", mock_start_task)

    messages = [
        {
            "role": "user",
            "content": "Refactor the entire authentication system and database models",
        }
    ]

    target, extra = await route_target(
        "autoconduck",
        messages,
        request=None,
        PSEUDO_MODELS={"autoconduck"},
        litellm_params_for=lambda t, c: {},
        normalize_messages_for_llm=lambda m: m,
    )

    assert mock_start_task.called
    assert "_oma_result" in extra
    assert (
        extra["_oma_result"]["report"]
        == "Refactoring completed by OMA subagents"
    )
    assert extra["_stats_selection"]["oma"]["outcomes"] == ["started", "completed"]


@pytest.mark.asyncio
async def test_explicit_refactor_reaches_oma_when_slm_returns_chat(monkeypatch):
    """Deterministic refactor intent reaches OMA without a real Node sidecar."""
    import autoconduck.config.manager as m

    cfg = _cfg_with_oma()
    m._config = cfg

    def incorrect_chat(self, messages, config=None):
        return {
            "confidence": 0.85,
            "task_type": "chat",
            "complexity_score": 1,
            "rationale": "incorrect SLM classification",
        }

    mock_start_task = AsyncMock(
        return_value={
            "status": "ok",
            "runner_started": True,
            "report": "OMA received the explicit refactor",
        }
    )
    monkeypatch.setattr(SLMPlanner, "_raw_infer", incorrect_chat)
    monkeypatch.setattr("autoconduck.plugin.runtime.start_task", mock_start_task)

    _target, extra = await route_target(
        "autoconduck",
        [{"role": "user", "content": "Refactor the router end-to-end."}],
        request=None,
        PSEUDO_MODELS={"autoconduck"},
        litellm_params_for=lambda t, c: {},
        normalize_messages_for_llm=lambda m: m,
    )

    mock_start_task.assert_awaited_once()
    assert extra["_oma_result"]["report"] == "OMA received the explicit refactor"
    assert extra["_stats_selection"]["oma"]["outcomes"] == ["started", "completed"]


@pytest.mark.asyncio
async def test_low_complexity_bypasses_oma(monkeypatch):
    """Low complexity prompt ('hi') routes to standard model pool without triggering OMA."""
    import autoconduck.config.manager as m

    cfg = _cfg_with_oma()
    m._config = cfg

    mock_start_task = AsyncMock(
        return_value={
            "status": "ok",
            "report": "OMA report",
        }
    )
    monkeypatch.setattr("autoconduck.plugin.runtime.start_task", mock_start_task)

    messages = [{"role": "user", "content": "hi"}]

    target, extra = await route_target(
        "autoconduck",
        messages,
        request=None,
        PSEUDO_MODELS={"autoconduck"},
        litellm_params_for=lambda t, c: {},
        normalize_messages_for_llm=lambda m: m,
    )

    assert not mock_start_task.called
    assert "_oma_result" not in extra
    assert target is not None
    assert extra["_stats_selection"]["oma"] == {
        "outcomes": ["not_eligible"],
        "reason": "complexity_below_threshold",
    }


@pytest.mark.asyncio
async def test_recursion_header_bypasses_oma(monkeypatch):
    """x-autoconduck-depth >= 1 or x-oma-sidecar=1 bypasses OMA gating to prevent infinite loops."""
    import autoconduck.config.manager as m

    cfg = _cfg_with_oma()
    m._config = cfg

    mock_start_task = AsyncMock()
    monkeypatch.setattr("autoconduck.plugin.runtime.start_task", mock_start_task)

    messages = [
        {
            "role": "user",
            "content": "Refactor the entire authentication system and database models",
        }
    ]

    # Case 1: x-autoconduck-depth: 1
    req1 = DummyRequest({"x-autoconduck-depth": "1"})
    target1, extra1 = await route_target(
        "autoconduck",
        messages,
        request=req1,
        PSEUDO_MODELS={"autoconduck"},
        litellm_params_for=lambda t, c: {},
        normalize_messages_for_llm=lambda m: m,
    )
    assert not mock_start_task.called
    assert "_oma_result" not in extra1
    assert extra1["_stats_selection"]["oma"] == {
        "outcomes": ["not_eligible"],
        "reason": "request_depth",
    }

    # Case 2: x-oma-sidecar: 1
    req2 = DummyRequest({"x-oma-sidecar": "1"})
    target2, extra2 = await route_target(
        "autoconduck",
        messages,
        request=req2,
        PSEUDO_MODELS={"autoconduck"},
        litellm_params_for=lambda t, c: {},
        normalize_messages_for_llm=lambda m: m,
    )
    assert not mock_start_task.called
    assert "_oma_result" not in extra2
    assert extra2["_stats_selection"]["oma"] == {
        "outcomes": ["not_eligible"],
        "reason": "oma_sidecar_header",
    }


@pytest.mark.asyncio
async def test_fail_soft_when_oma_fails(monkeypatch):
    """If OMA runner raises exception or returns status=error, degrades fail-soft to standard routing."""
    import autoconduck.config.manager as m

    cfg = _cfg_with_oma()
    m._config = cfg

    # Exception case
    mock_start_task_exc = AsyncMock(
        side_effect=RuntimeError("Node sidecar process crashed")
    )
    monkeypatch.setattr(
        "autoconduck.plugin.runtime.start_task", mock_start_task_exc
    )

    messages = [
        {
            "role": "user",
            "content": "Refactor the entire authentication system",
        }
    ]

    target, extra = await route_target(
        "autoconduck",
        messages,
        request=None,
        PSEUDO_MODELS={"autoconduck"},
        litellm_params_for=lambda t, c: {},
        normalize_messages_for_llm=lambda m: m,
    )

    assert "_oma_result" not in extra
    assert target is not None
    assert extra["_stats_selection"]["oma"] == {
        "outcomes": ["failed_soft"],
        "reason": "runner_exception",
    }

    # Error status return case
    mock_start_task_err = AsyncMock(
        return_value={
            "status": "error",
            "runner_started": True,
            "report": "OMA sidecar launch failed: script not found",
        }
    )
    monkeypatch.setattr(
        "autoconduck.plugin.runtime.start_task", mock_start_task_err
    )

    target2, extra2 = await route_target(
        "autoconduck",
        messages,
        request=None,
        PSEUDO_MODELS={"autoconduck"},
        litellm_params_for=lambda t, c: {},
        normalize_messages_for_llm=lambda m: m,
    )

    assert "_oma_result" not in extra2
    assert target2 is not None
    assert extra2["_stats_selection"]["oma"] == {
        "outcomes": ["started", "failed_soft"],
        "reason": "runner_error",
    }


@pytest.mark.asyncio
async def test_oma_never_returns_completed_result_without_runner_evidence(monkeypatch):
    """An unproven runner must fail soft instead of returning an OMA completion."""
    import autoconduck.config.manager as m

    cfg = _cfg_with_oma()
    m._config = cfg
    monkeypatch.setattr(
        "autoconduck.plugin.runtime.start_task",
        AsyncMock(return_value={"status": "ok", "report": "unverified result"}),
    )

    target, extra = await route_target(
        "autoconduck",
        [{"role": "user", "content": "Refactor the router end-to-end."}],
        request=None,
        PSEUDO_MODELS={"autoconduck"},
        litellm_params_for=lambda t, c: {},
        normalize_messages_for_llm=lambda m: m,
    )

    assert target is not None
    assert "_oma_result" not in extra
    assert extra["_stats_selection"]["oma"] == {
        "outcomes": ["failed_soft"],
        "reason": "runner_error",
    }


def test_oma_chat_completion_http_endpoint(monkeypatch):
    """End-to-end HTTP test: high complexity chat completion returns OMA report."""
    import autoconduck.config.manager as m
    from autoconduck import main

    cfg = _cfg_with_oma()
    m._config = cfg

    mock_start_task = AsyncMock(
        return_value={
            "task_id": "task_http",
            "status": "ok",
            "runner_started": True,
            "report": "OMA subagents completed full refactor workflow",
            "mode": "auto",
        }
    )
    monkeypatch.setattr("autoconduck.plugin.runtime.start_task", mock_start_task)

    main._build()
    client = TestClient(main.app)

    res = client.post(
        "/v1/chat/completions",
        json={
            "model": "autoconduck",
            "messages": [
                {
                    "role": "user",
                    "content": "Refactor the entire authentication system",
                }
            ],
            "stream": False,
        },
    )

    assert res.status_code == 200
    data = res.json()
    assert (
        data["choices"][0]["message"]["content"]
        == "OMA subagents completed full refactor workflow"
    )
    from autoconduck.stats import aggregate, flush_stats, load_records

    flush_stats()
    assert aggregate(load_records())["oma"]["outcomes"] == {
        "started": 1,
        "completed": 1,
    }
