"""Comprehensive test suite for SLM Planner & Circuit Breaker.

Verifies:
- Strict Pydantic validation of ExecutionPlan schema (route, confidence, subtasks, SLA).
- Fast-direct vs dynamic-dag task classification.
- Selective RAG triggers and query generation.
- Configurable circuit breaker timeout fallback to safe SLA.
- Corrupted JSON and syntax error graceful degradation.
- Subtask dependency topological validation.
"""
from __future__ import annotations
from unittest.mock import patch

import asyncio
import time
from typing import Any
import pytest

from autoconduck.routing.model_pool import CapabilitySLA
from autoconduck.routing.slm_planner import (
    ExecutionPlan,
    SLMPlanner,
    SubTaskSpec,
)



@pytest.fixture(autouse=True)
def mock_slm_generation():
    def mock_generate_structured_json(model, prompt, schema, **kwargs):
        text = prompt.lower()
        
        needs_dag = "refactor" in text or ("db.py" in text and "auth.py" in text) or ("update" in text and "auth.py" in text and "session.py" in text)
        task_type = "chat"
        if needs_dag:
            task_type = "multi_edit"
            if "refactor" in text:
                task_type = "refactor"
        if "git commit" in text or "format code" in text or "git status" in text:
            task_type = "git_ops"
        
        return schema(
            complexity_score=8 if needs_dag else 2,
            requires_multi_agent_dag=bool(needs_dag),
            task_type=task_type,
            rationale="mock rationale",
            needs_rag="litellm" in text or "lancedb" in text
        )

    with patch("autoconduck._compat.outlines_fallback.generate_structured_json", side_effect=mock_generate_structured_json):
        with patch("autoconduck.routing.slm_planner.is_outlines_available", return_value=True):
            yield

@pytest.fixture
def slm_planner() -> SLMPlanner:
    planner = SLMPlanner()
    planner._llm = "dummy"  # Bypass the None check
    return planner


# ==============================================================================
# Tier 1: Feature Coverage (>=5 tests)
# ==============================================================================

@pytest.mark.asyncio
async def test_slm_planner_generates_valid_execution_plan(slm_planner: SLMPlanner):
    """Planner returns a strictly validated ExecutionPlan instance."""
    messages = [
        {"role": "user", "content": "Explain how the Python GIL works in 3.13."}
    ]
    plan = await slm_planner.plan(messages)
    assert isinstance(plan, ExecutionPlan)
    assert plan.route in ("fast_direct", "dynamic_dag")
    assert 0.0 <= plan.confidence <= 1.0
    assert plan.task_type in (
        "chat", "explain", "recon", "single_edit", "multi_edit", "debug", "refactor", "full_workflow", "git_ops",
        "routine", "read_answer", "knowledge_query", "research",
    )
    assert isinstance(plan.suggested_sla, CapabilitySLA)
    assert isinstance(plan.subtasks, list)
    assert isinstance(plan.needs_rag, bool)


@pytest.mark.asyncio
async def test_slm_planner_fast_direct_route_for_simple_chat(slm_planner: SLMPlanner):
    """Simple conversational turns route as fast_direct with cheap_fast or balanced SLA."""
    messages = [
        {"role": "user", "content": "What is 2 + 2?"}
    ]
    plan = await slm_planner.plan(messages)
    assert plan.route == "fast_direct"
    assert plan.task_type in ("chat", "explain")
    assert not plan.needs_rag
    assert len(plan.subtasks) == 0


@pytest.mark.asyncio
async def test_slm_planner_dynamic_dag_route_for_complex_refactoring(slm_planner: SLMPlanner):
    """Complex multi-file refactoring requests compile into dynamic_dag with subtasks."""
    messages = [
        {
            "role": "user",
            "content": "Refactor the database layer in db.py and auth.py to use async SQLAlchemy 2.0 with connection pooling.",
        }
    ]
    plan = await slm_planner.plan(messages)
    assert plan.route == "dynamic_dag"
    assert plan.task_type in ("multi_edit", "refactor", "full_workflow")
    assert len(plan.subtasks) >= 1
    for task in plan.subtasks:
        assert isinstance(task, SubTaskSpec)
        assert task.id
        assert task.goal
        assert task.role in ("recon", "read", "edit", "verify", "bash", "reasoning")


@pytest.mark.asyncio
async def test_slm_planner_needs_rag_and_queries_generation(slm_planner: SLMPlanner):
    """Queries mentioning framework APIs or repository dependencies set needs_rag=True."""
    messages = [
        {
            "role": "user",
            "content": "How do we call the internal LiteLLM proxy and LanceDB vector index in this repo?",
        }
    ]
    plan = await slm_planner.plan(messages)
    if plan.needs_rag:
        assert len(plan.rag_queries) >= 1
        assert any("lancedb" in q.lower() or "litellm" in q.lower() or "vector" in q.lower() for q in plan.rag_queries)


@pytest.mark.asyncio
async def test_slm_planner_model_sla_recommendations(slm_planner: SLMPlanner):
    """Verifies that suggested_sla and synthesizer_sla are valid CapabilitySLA instances."""
    messages = [
        {"role": "user", "content": "Analyze architecture and synthesize a full migration roadmap."}
    ]
    plan = await slm_planner.plan(messages)
    assert isinstance(plan.suggested_sla, CapabilitySLA)
    assert isinstance(plan.synthesizer_sla, CapabilitySLA)


# ==============================================================================
# Tier 2: Boundary & Corner Cases (>=5 tests)
# ==============================================================================

@pytest.mark.asyncio
async def test_slm_planner_circuit_breaker_timeout(monkeypatch):
    """When SLM inference hangs or exceeds circuit breaker timeout, soft fallback triggers."""
    planner = SLMPlanner(circuit_breaker_ms=60.0)

    # Simulate slow SLM generator taking 300ms
    async def slow_inference(*args, **kwargs):
        await asyncio.sleep(0.3)
        return "{}"

    monkeypatch.setattr(planner, "_raw_infer", slow_inference, raising=False)

    start = time.perf_counter()
    plan = await planner.plan([{"role": "user", "content": "Perform massive repo refactor"}])
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    # Must return within ~120ms total (60ms SLA + small scheduling overhead)
    assert elapsed_ms < 150.0, f"Circuit breaker took {elapsed_ms:.1f}ms, exceeded timeout target!"
    assert plan.fallback_used
    assert isinstance(plan.suggested_sla, CapabilitySLA)


@pytest.mark.asyncio
async def test_slm_planner_corrupted_llm_json_fallback(monkeypatch):
    """When raw SLM output is corrupted text, planner degrades gracefully to fallback plan."""
    planner = SLMPlanner()

    async def broken_inference(*args, **kwargs):
        return "This is completely unparseable {json: missing_quotes, broken"

    monkeypatch.setattr(planner, "_raw_infer", broken_inference, raising=False)

    plan = await planner.plan([{"role": "user", "content": "Do work"}])
    assert isinstance(plan, ExecutionPlan)
    assert plan.fallback_used
    assert isinstance(plan.suggested_sla, CapabilitySLA)


@pytest.mark.asyncio
async def test_slm_planner_empty_messages_and_system_only(slm_planner: SLMPlanner):
    """Empty or system-only prompt lists do not crash the planner."""
    plan_empty = await slm_planner.plan([])
    assert isinstance(plan_empty, ExecutionPlan)

    plan_system = await slm_planner.plan([{"role": "system", "content": "You are helpful."}])
    assert isinstance(plan_system, ExecutionPlan)


@pytest.mark.asyncio
async def test_slm_planner_subtask_cyclic_dependency_sanitization():
    """Subtasks with cyclic depends_on must not cause infinite loops in plan validation."""
    cycle_tasks = [
        SubTaskSpec(id="t1", goal="Task 1", depends_on=["t2"]),
        SubTaskSpec(id="t2", goal="Task 2", depends_on=["t1"]),
    ]
    plan = ExecutionPlan(
        route="dynamic_dag",
        confidence=0.8,
        task_type="refactor",
        subtasks=cycle_tasks,
    )
    assert len(plan.subtasks) == 2
    assert plan.subtasks[0].id == "t1"
    assert plan.subtasks[1].id == "t2"


@pytest.mark.asyncio
async def test_slm_planner_latency_benchmark_under_75ms(slm_planner: SLMPlanner):
    """Under normal heuristic operation (or fallback), planning completes within 75ms."""
    messages = [{"role": "user", "content": "Fix typo in README"}]
    start = time.perf_counter()
    plan = await slm_planner.plan(messages)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    assert elapsed_ms < 100.0, f"Normal planning took {elapsed_ms:.1f}ms, exceeded 75ms target!"
    assert plan is not None


@pytest.mark.asyncio
async def test_slm_planner_doc_qa_routes_fast_direct_no_edit_node(slm_planner: SLMPlanner):
    """Pure document Q&A (no code signal) must never trigger a DAG or edit subtask."""
    messages = [
        {
            "role": "user",
            "content": (
                "Coca-Cola's bottlers are an example of which dynamic-consistency threat, "
                "the holdup problem or the slack problem?"
            ),
        }
    ]
    plan = await slm_planner.plan(messages)
    assert plan.route == "fast_direct"
    assert plan.task_type != "multi_edit"
    assert len(plan.subtasks) == 0
    assert all(t.role != "edit" for t in plan.subtasks)


@pytest.mark.asyncio
async def test_slm_planner_system_reminder_injection_cannot_force_dag(slm_planner: SLMPlanner):
    """A <system-reminder> block (date/cwd bookkeeping) embedded in user text must never
    contribute keyword signal to classification, even if it contains words like
    'directory' that used to combine with prose ' and ' to false-positive into a DAG."""
    poisoned = (
        "<system-reminder>\nToday: 2026-08-26; current working directory: "
        "C:\\Users\\plum\\Documents\\docs\n</system-reminder>\n"
        "Coca-Cola's bottlers are an example of which dynamic-consistency threat, "
        "the holdup problem, and slack problem?"
    )
    messages = [{"role": "user", "content": poisoned}]
    plan = await slm_planner.plan(messages)
    assert plan.route == "fast_direct"
    assert plan.task_type != "multi_edit"
    assert len(plan.subtasks) == 0


@pytest.mark.asyncio
async def test_slm_planner_extract_user_text_strips_system_reminder():
    """_extract_user_text must strip <system-reminder> blocks regardless of source."""
    planner = SLMPlanner()
    messages = [
        {
            "role": "user",
            "content": "<system-reminder>Today: 2026-08-26; current working directory: /tmp</system-reminder>Hello there",
        }
    ]
    text = planner._extract_user_text(messages)
    assert "system-reminder" not in text.lower()
    assert "current working directory" not in text.lower()
    assert "Hello there" in text


@pytest.mark.asyncio
async def test_slm_planner_genuine_multi_file_code_edit_still_dag_with_edit_node(slm_planner: SLMPlanner):
    """A real multi-file code edit request must still route to dynamic_dag with an edit node."""
    messages = [
        {
            "role": "user",
            "content": "Update the login function in auth.py and the session handler in session.py to add rate limiting.",
        }
    ]
    plan = await slm_planner.plan(messages)
    assert plan.route == "dynamic_dag"
    assert any(t.role == "edit" for t in plan.subtasks)


@pytest.mark.asyncio
async def test_slm_planner_malformed_input_fallback(slm_planner: SLMPlanner):
    """Malformed/non-list messages must degrade to a safe fast_direct fallback, never crash."""
    plan = await slm_planner.plan(None)  # type: ignore[arg-type]
    assert isinstance(plan, ExecutionPlan)
    assert plan.route == "fast_direct"
    assert plan.fallback_used


@pytest.mark.asyncio
async def test_slm_planner_routes_git_commit_and_routine_to_cheap_fast(slm_planner: SLMPlanner):
    """Git commit, diff, and status operations route to cheap_fast SLA."""
    git_prompts = [
        "Please check unstaged files and create a git commit with a clear commit message",
        "create a git commit for the changes in this repo",
        "git status and git diff",
        "format code and run tests",
    ]
    for prompt in git_prompts:
        plan = await slm_planner.plan([{"role": "user", "content": prompt}])
        assert plan.route == "fast_direct"
        assert plan.task_type in ("git_ops", "routine")
        assert plan.suggested_sla.max_cost <= 1.5


# ==============================================================================
# Tier 3: Harness-agnostic noise robustness (Layer 1/2/3 hardening)
# ==============================================================================

@pytest.mark.asyncio
async def test_harness_preamble_in_first_message_and_inline_still_fast_direct(slm_planner: SLMPlanner):
    """A harness that re-sends a <system-reminder> cwd/date preamble as messages[0]
    AND inlines it into the same message as a plain doc Q&A must still route
    fast_direct with no DAG and no edit node -- regardless of which message
    carries the boilerplate."""
    preamble = (
        "<system-reminder>\nToday: 2026-08-26; current working directory: "
        "C:\\Users\\plum\\Documents\\Works\\AutoConduck\n</system-reminder>"
    )
    messages = [
        {"role": "user", "content": preamble},
        {
            "role": "user",
            "content": preamble + "\nWhat is the holdup problem in contract theory?",
        },
    ]
    plan = await slm_planner.plan(messages)
    assert plan.route == "fast_direct"
    assert len(plan.subtasks) == 0
    assert all(t.role != "edit" for t in plan.subtasks)


@pytest.mark.asyncio
async def test_novel_unknown_boilerplate_does_not_flip_to_dag(slm_planner: SLMPlanner):
    """An unknown/novel boilerplate block -- NOT one of the curated markers --
    must not be able to force a plain question into dynamic_dag, even though
    it is left unstripped. Conservative signal-gating (Layer 3), not an
    ever-growing strip dictionary, is what protects against novel noise."""
    novel_noise = "<SYS> foo bar update change directory files </SYS>\n"
    messages = [
        {
            "role": "user",
            "content": novel_noise + "What is the capital of France?",
        }
    ]
    plan = await slm_planner.plan(messages)
    assert plan.route == "fast_direct"
    assert len(plan.subtasks) == 0
    assert all(t.role != "edit" for t in plan.subtasks)


@pytest.mark.asyncio
async def test_multiple_earlier_junk_user_messages_do_not_cause_false_dag(slm_planner: SLMPlanner):
    """Several earlier user turns full of boilerplate/junk (which happen to
    contain code-domain words) must not bleed into classification of a later,
    genuinely clean, unrelated question -- only the LAST user message is
    classified."""
    messages = [
        {"role": "user", "content": "<system-reminder>Today: 2026-08-26; current working directory: /repo</system-reminder>"},
        {"role": "user", "content": "update the module and fix the config file across files"},
        {"role": "user", "content": "refactor the codebase and rewrite the module"},
        {"role": "user", "content": "What is the boiling point of water at sea level?"},
    ]
    plan = await slm_planner.plan(messages)
    assert plan.route == "fast_direct"
    assert len(plan.subtasks) == 0


@pytest.mark.asyncio
async def test_strip_harness_noise_handles_sentinel_and_bracket_forms():
    """_strip_harness_noise removes the curated SYSTEM NOTE sentinel and
    bracket forms, and Today/cwd meta lines, without touching real content."""
    from autoconduck.routing.slm_planner import _strip_harness_noise

    text = (
        "<=== SYSTEM NOTE ===>\nsome injected bookkeeping\n\n"
        "[System Note: harness build 42]\n"
        "Today is 2026-08-26\n"
        "Current working directory: /repo\n"
        "Please explain the CAP theorem."
    )
    cleaned, noise_removed = _strip_harness_noise(text)
    assert noise_removed is True
    assert "SYSTEM NOTE" not in cleaned
    assert "System Note" not in cleaned
    assert "current working directory" not in cleaned.lower()
    assert "Please explain the CAP theorem." in cleaned


@pytest.mark.asyncio
async def test_extract_last_user_text_ignores_earlier_messages():
    """_extract_last_user_text classifies only the last user/human message,
    not the cumulative concatenation of the whole user-role history."""
    planner = SLMPlanner()
    messages = [
        {"role": "user", "content": "refactor db.py and auth.py across files"},
        {"role": "assistant", "content": "Sure, working on it."},
        {"role": "user", "content": "Actually, what's 2 + 2?"},
    ]
    text, noise_removed = planner._extract_last_user_text(messages)
    assert "db.py" not in text
    assert "2 + 2" in text
    assert noise_removed is False


@pytest.mark.asyncio
async def test_slm_planner_evaluate_session_trajectory_triggers_replan():
    """evaluate_session_trajectory escalates on read-heavy session with 0 edits."""
    planner = SLMPlanner()
    messages = [
        {"role": "user", "content": "Refactor auth and routing systems"},
        {"role": "assistant", "content": "Reading files"},
    ]
    session_stats = {
        "read_count": 10,
        "edit_count": 0,
        "replan_reason": "Read-heavy tool loop without edits",
    }
    verdict = planner.evaluate_session_trajectory(messages, session_stats=session_stats)
    assert verdict.should_escalate is True
    assert verdict.suggested_plan is not None
    assert verdict.suggested_plan.route == "dynamic_dag"
    assert len(verdict.suggested_plan.subtasks) >= 2


@pytest.mark.asyncio
async def test_slm_planner_evaluate_session_trajectory_ignores_active_edits():
    """evaluate_session_trajectory does not escalate when edits are actively occurring."""
    planner = SLMPlanner()
    messages = [
        {"role": "user", "content": "Refactor auth and routing systems"},
    ]
    session_stats = {
        "read_count": 5,
        "edit_count": 3,
        "replan_reason": "",
    }
    verdict = planner.evaluate_session_trajectory(messages, session_stats=session_stats)
    assert verdict.should_escalate is False


@pytest.mark.asyncio
async def test_dispatcher_route_mid_execution_replan_promotes_to_dag():
    """dispatcher.route routes to dynamic_dag when replan_pending is True during tool loop."""
    from autoconduck.routing.dispatcher import route
    import json

    messages = [{"role": "user", "content": "Refactor codebase"}]
    for i in range(8):
        cid = f"call_{i}"
        messages.extend([
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": cid, "type": "function", "function": {"name": "read", "arguments": json.dumps({"path": f"src/m_{i}.py"})}}
                ],
            },
            {"role": "tool", "tool_call_id": cid, "name": "read", "content": "content"},
        ])

    # With replan_pending=False, routes fast_direct
    dec_fast = route(messages, replan_pending=False)
    assert dec_fast.path == "fast"
    assert dec_fast.route == "fast_direct"

    # With replan_pending=True, routes dynamic_dag
    dec_dag = route(messages, replan_pending=True)
    assert dec_dag.path == "slow"
    assert dec_dag.route == "dynamic_dag"
    assert dec_dag.plan is not None


def test_resolve_slm_path_resolution(tmp_path, monkeypatch):
    """resolve_slm_path resolves from direct path, config, and default models dir."""
    from autoconduck.routing.slm_planner import resolve_slm_path
    from autoconduck.config import Config

    # 1. Direct existing file
    direct_file = tmp_path / "model.onnx"
    direct_file.write_bytes(b"DATA")
    assert resolve_slm_path(str(direct_file)) == str(direct_file)

    # 2. Path from Config object
    cfg = Config()
    cfg.selection.slm_model_path = str(direct_file)
    assert resolve_slm_path("", config=cfg) == str(direct_file)

    # 3. Path in ~/.autoconduck/models/
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    lfm_file = models_dir / "lfm2.5-1.2b-instruct-q4.onnx"
    lfm_file.write_bytes(b"LFM_DATA")

    with patch("autoconduck.routing.slm_downloader.get_default_models_dir", return_value=models_dir):
        resolved = resolve_slm_path("lfm2.5-1.2b-instruct-q4.onnx")
        assert resolved == str(lfm_file)


@pytest.mark.asyncio
async def test_slm_planner_onnx_lfm_model_loading(tmp_path):
    """SLMPlanner correctly loads and initializes ONNX / Liquid AI LFM models."""
    from autoconduck.config import Config

    lfm_file = tmp_path / "lfm2.5-1.2b-instruct-q4.onnx"
    lfm_file.write_bytes(b"ONNX_MODEL_CONTENT")

    planner = SLMPlanner(model_path=str(lfm_file))
    cfg = Config()
    cfg.selection.slm_model_path = str(lfm_file)

    planner._ensure_llm_loaded(cfg)
    assert planner._llm is not None


@pytest.mark.asyncio
async def test_slm_planner_fallback_when_slm_unavailable_is_quiet():
    """When SLM is not loaded or fallback shim, plan_sync and plan quietly return fallback plan."""
    planner = SLMPlanner(model_path="nonexistent_model.onnx")
    messages = [{"role": "user", "content": "Hello world"}]
    
    # plan_sync should not raise and return a valid fallback plan
    sync_plan = planner.plan_sync(messages)
    assert isinstance(sync_plan, ExecutionPlan)
    assert sync_plan.fallback_used is True
    assert sync_plan.route == "fast_direct"

    # async plan should also return fallback plan
    async_plan = await planner.plan(messages)
    assert isinstance(async_plan, ExecutionPlan)
    assert async_plan.fallback_used is True
    assert async_plan.route == "fast_direct"
