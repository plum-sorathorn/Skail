"b""Comprehensive prompt evaluation, multi-tier routing, Turn Guard, and Plugin escalation test suite."""
from __future__ import annotations

import time
import pytest
from pathlib import Path

from autoconduck.config.models import Config, ModelEntry, PluginConfig, SelectionConfig
from autoconduck.plugin.bias import SessionBiasStore, get_bias_store
from autoconduck.plugin.ledger import PluginLedger, get_ledger
from autoconduck.routing.dispatcher import route
from autoconduck.routing.model_pool import CapabilitySLA
from autoconduck.server.turn_guard import TurnGuard, TurnAction

TEST_MODELS = [
    ModelEntry(
        id="mock/gpt-4o-mini",
        provider="openai",
        price_in=0.15,
        price_out=0.60,
        cost_input=0.15,
        cost_output=0.60,
        context_window=128000,
        supports_tools=True,
        is_reasoning=False,
        capability_score=0.35,
        capability_vector={
            "reasoning": 0.35,
            "tool_reliability": 0.50,
            "code_quality": 0.35,
            "latency_class": 0.85,
        },
    ),
    ModelEntry(
        id="mock/claude-3-5-haiku",
        provider="anthropic",
        price_in=0.80,
        price_out=4.00,
        cost_input=0.80,
        cost_output=4.00,
        context_window=200000,
        supports_tools=True,
        is_reasoning=False,
        capability_score=0.52,
        capability_vector={
            "reasoning": 0.50,
            "tool_reliability": 0.65,
            "code_quality": 0.55,
            "latency_class": 0.75,
        },
    ),
    ModelEntry(
        id="mock/deepseek-chat-v3",
        provider="deepseek",
        price_in=0.27,
        price_out=1.10,
        cost_input=0.27,
        cost_output=1.10,
        context_window=64000,
        supports_tools=True,
        is_reasoning=False,
        capability_score=0.68,
        capability_vector={
            "reasoning": 0.65,
            "tool_reliability": 0.60,
            "code_quality": 0.75,
            "latency_class": 0.55,
        },
    ),
    ModelEntry(
        id="mock/claude-3-5-sonnet",
        provider="anthropic",
        price_in=3.00,
        price_out=15.00,
        cost_input=3.00,
        cost_output=15.00,
        context_window=200000,
        supports_tools=True,
        is_reasoning=False,
        capability_score=0.86,
        capability_vector={
            "reasoning": 0.85,
            "tool_reliability": 0.85,
            "code_quality": 0.88,
            "latency_class": 0.45,
        },
    ),
    ModelEntry(
        id="mock/o3-mini",
        provider="openai",
        price_in=1.10,
        price_out=4.40,
        cost_input=1.10,
        cost_ouput=4.40,
        context_window=200000,
        supports_tools=True,
        is_reasoning=True,
        capability_score=0.82,
        capability_vector={
            "reasoning": 0.92,
            "tool_reliability": 0.70,
            "code_quality": 0.80,
            "latency_class": 0.35,
        },
    ),
    ModelEntry(
        id="mock/claude-3-opus",
        provider="anthropic",
        price_in=15.00,
        price_out=75.00,
        cost_input=15.00,
        cost_output=75.00,
        context_window=200000,
        supports_tools=True,
        is_reasoning=True,
        capability_score=0.94,
        capability_vector={
            "reasoning": 0.95,
            "tool_reliability": 0.90,
            "code_quality": 0.92,
            "latency_class": 0.20,
        },
    ),
]


@pytest.fixture
def eval_config() -> Config:
    return Config(
        models={m.id: m for m in TEST_MODELS},
        model_list=[m.model_dump() for m in TEST_MODELS],
        selection=SelectionConfig(
            confidence_floor_k=0.15,
            confidence_floor_max=0.60,
        ),
        plugins=PluginConfig(
            enabled=True,
            escalation_floor_bump=0.15,
            escalation_ttl_turns=10,
        ),
    )


def test_prompt_spectrum_routing_decisions(eval_config: Config) -> None:
    prompts = [
        "Hello! What can you help me with today?",
        "Explain how Python GIL works.",
        "git status and check staged files",
        "Search codebase for all occurrences of API_KEY",
        "Fix the typo on line 42 in utils.py",
        "Implement rate limiting middleware with tests",
        "Debug this traceback: TypeError: object is not subscriptable",
        "Refactor monolithic server into async worker pool with SQLite WAL",
    ]

    for p in prompts:
        messages = [{"role": "user", "content": p}]
        dec = route(messages, config=eval_config)
        assert dec is not None
        assert dec.model is not None
        assert dec.path == "fast"
        assert dec.confidence > 0.0


def test_turn_guard_tool_loop_bypass_latency(eval_config: Config) -> None:
    tool_loop_messages = [
        {"role": "user", "content": "Refactor auth.py and fix tests"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{\"path\": \"auth.py\"}'},
                }
            ],
        },
        {"role": "tool", "name": "read_file", "content": "def auth(): return True"},
    ]

    guard = TurnGuard()
    t0 = time.perf_counter()
    res = guard.classify_turn(tool_loop_messages)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert elapsed_ms < 2.0  # <2ms invariant
    assert res.is_tool_loop is True
    assert res.target_action == TurnAction.DIRECT_ACTIVE_TIER

    dec = route(tool_loop_messages, config=eval_config)
    assert dec.model is not None
    assert "tool_loop_bypass" in dec.reason


def test_plugin_stagnation_multi_tier_elevation(eval_config: Config) -> None:
    session_id = "test-session-multi-tier-eval"
    bias_store = get_bias_store()
    bias_store.reset_session(session_id)

    prompt = [{"role": "user", "content": "Refactor database engine for multi-tenant sharding"}]

    # Base turn
    base_dec = route(prompt, config=eval_config, session_id=session_id)
    assert base_dec.model == "mock/gpt-4o-mini"
    assert base_dec.min_capability_score_applied == 0.0

    # Step 1: Stagnation level 1 ++0.25 floor bump)
    bias_store.apply_escalation(session_id, bump=0.25, ttl_turns=5)
    dec_tier1 = route(prompt, config=eval_config, session_id=session_id)
    assert dec_tier1.min_capability_score_applied == 0.25

    # Step 2: Severe stagnation level 2 ++0.55 floor bump)
    bias_store.apply_escalation(session_id, bump=0.55, ttl_turns=5)
    dec_tier2 = route(prompt, config=eval_config, session_id=session_id)
    assert dec_tier2.min_capability_score_applied == 0.55
    assert dec_tier2.model == "mock/deepseek-chat-v3"

    # Step 3: Emergency escalation (+0.75 hard cap)
    bias_store.apply_escalation(session_id, bump=0.75, ttl_turns=5)
    dec_tier3 = route(prompt, config=eval_config, session_id=session_id)
    assert dec_tier3.min_capability_score_applied == 0.75
    assert dec_tier3.model == "mock/o3-mini"


def test_pseudo_model_variants_routing(eval_config: Config) -> None:
    prompt = [{"role": "user", "content": "Write an architectural design spec"}]

    dec_budget = route(prompt, config=eval_config, pseudo_model="autoconduck-budget")
    assert dec_budget.model == "mock/gpt-4o-mini"

    dec_default = route(prompt, config=eval_config, pseudo_model="autoconduck")
    assert dec_default.model == "mock/gpt-4o-mini"

    dec_expensive = route(prompt, config=eval_config, pseudo_model="autoconduck-expensive")
    assert dec_expensive.model in ("mock/deepseek-chat-v3", "mock/claude-3-opus", "mock/claude-3-5-sonnet")


def test_plugin_ledger_durability() -> None:
    session_id = "test-session-ledger-durability"
    ledger = get_ledger()

    ledger.enqueue(session_id, "task-eval-1", "task_start", {"goal": "evaluate routing"})
    ledger.enqueue(session_id, "task-eval-1", "escalation", {"reason": "consecutive_errors", "bump": 0.25})
    ledger.flush_sync()

    events = ledger.query_events(session_id=session_id)
    assert len(events) >= 2
    kinds = [e.get("kind") for e in events]
    assert "task_start" in kinds
    assert "escalation" in kinds


@pytest.mark.asyncio
async def test_server_startup_prewarms_slm() -> None:
    """Verify that lifespan startup loads and warms the SLM before ready."""
    from autoconduck.server.server_streaming import _get_app
    from autoconduck.routing.slm_planner import _GLOBAL_LLM_CACHE

    app = _get_app()
    lifespan = getattr(app.router, "lifespan_context", None)
    assert lifespan is not None

    async with lifespan(app):
        # Inside running lifespan, SLM should be loaded in cache
        from autoconduck.routing.slm_downloader import get_default_models_dir
        models_dir = get_default_models_dir()
        qwen_path = str(models_dir / "qwen2.5-coder-0.5b-instruct-q4.onnx")
        if Path(qwen_path).exists():
            assert qwen_path in _GLOBAL_LLM_CACHE
            cached_model = _GLOBAL_LLM_CACHE[qwen_path]
            assert cached_model is not None
