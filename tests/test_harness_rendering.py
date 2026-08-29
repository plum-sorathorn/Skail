from __future__ import annotations

import pytest
from autoconduck.routing.slm_planner import ExecutionPlan, SubTaskSpec
from autoconduck.harnesses import (
    resolve_adapter_for_request,
    OmpAdapter,
    ClaudeCodeAdapter,
    OpenCodeAdapter,
    PiAdapter,
    GenericAdapter,
)


@pytest.fixture
def sample_plan() -> ExecutionPlan:
    return ExecutionPlan(
        route="dynamic_dag",
        confidence=0.9,
        task_type="refactor",
        subtasks=[
            SubTaskSpec(id="recon", goal="Analyze auth module structure", role="recon", scope=["autoconduck/auth.py"]),
            SubTaskSpec(id="read_session", goal="Read session store implementation", role="read", depends_on=["recon"]),
            SubTaskSpec(id="edit_middleware", goal="Implement rate limiting", role="edit", depends_on=["read_session"]),
        ],
        summary="Refactor auth and session rate limiting",
    )


def test_omp_adapter_render_plan(sample_plan):
    adapter = OmpAdapter()
    rendered = adapter.render_plan(sample_plan)
    assert "### AutoConduck Task Decomposition" in rendered
    assert "Agent 1 (recon)" in rendered
    assert "=> Analyze auth module structure" in rendered


def test_claude_code_adapter_render_plan(sample_plan):
    adapter = ClaudeCodeAdapter()
    rendered = adapter.render_plan(sample_plan)
    assert "[AUTOCONDUCK EXECUTION DIRECTIVE]" in rendered
    assert "Task(description=" in rendered
    assert "Analyze auth module structure" in rendered


def test_opencode_adapter_render_plan(sample_plan):
    adapter = OpenCodeAdapter()
    rendered = adapter.render_plan(sample_plan)
    assert "### OpenCode Multi-Agent Task Directives" in rendered
    assert "subagent(type=" in rendered


def test_pi_adapter_render_plan(sample_plan):
    adapter = PiAdapter()
    rendered = adapter.render_plan(sample_plan)
    assert "task(goal=" in rendered


def test_generic_adapter_render_plan(sample_plan):
    adapter = GenericAdapter()
    rendered = adapter.render_plan(sample_plan)
    assert "Execution Checklist:" in rendered
    assert "- [ ] Step 1: Analyze auth module structure" in rendered


def test_resolve_adapter_for_request():
    assert isinstance(resolve_adapter_for_request(client_type="omp"), OmpAdapter)
    assert isinstance(resolve_adapter_for_request(user_agent="omp/v18.0.0"), OmpAdapter)
    assert isinstance(resolve_adapter_for_request(client_type="claude_code"), ClaudeCodeAdapter)
    assert isinstance(resolve_adapter_for_request(user_agent="Claude-Code/0.2.0"), ClaudeCodeAdapter)
    assert isinstance(resolve_adapter_for_request(client_type="opencode"), OpenCodeAdapter)
    assert isinstance(resolve_adapter_for_request(client_type="pi"), PiAdapter)

    # Tool-based resolution
    assert isinstance(resolve_adapter_for_request(tools=[{"name": "Task"}]), ClaudeCodeAdapter)
    assert isinstance(resolve_adapter_for_request(tools=[{"name": "subagent"}]), OpenCodeAdapter)
    assert isinstance(resolve_adapter_for_request(tools=[{"name": "task"}]), OmpAdapter)

    # Fallback to generic
    assert isinstance(resolve_adapter_for_request(tools=[{"name": "read_file"}]), GenericAdapter)
