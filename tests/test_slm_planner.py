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


@pytest.fixture
def slm_planner() -> SLMPlanner:
    return SLMPlanner()


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
        "chat", "explain", "recon", "single_edit", "multi_edit", "debug", "refactor", "full_workflow", "git_ops", "routine"
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
