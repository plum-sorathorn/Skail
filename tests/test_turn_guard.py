"""Comprehensive test suite for Turn Guard (0ms tool loop classifier & stagnation escalation).

Verifies:
- Direct bypass to active tier for in-flight tool loops (<2ms latency).
- Stagnation escalation on 3+ identical tool calls.
- Stagnation escalation on 2+ consecutive tool execution errors.
- Streak counters, error tracking, and multi-format support (OpenAI & Anthropic).
- Edge cases: empty messages, malformed payloads, alternating errors.
"""
from __future__ import annotations

import json
import time
from typing import Any
import pytest

try:
    from autoconduck.server.turn_guard import TurnAction, TurnClassificationResult, TurnGuard
except ImportError:
    pytest.skip("autoconduck.server.turn_guard not yet implemented in this milestone", allow_module_level=True)


@pytest.fixture
def turn_guard() -> TurnGuard:
    return TurnGuard()


# ==============================================================================
# Tier 1: Feature Coverage (>=5 tests)
# ==============================================================================

def test_turn_guard_new_user_message_routes_to_slm(turn_guard: TurnGuard):
    """Clean initial user prompt routes to SLM Planner."""
    messages = [
        {"role": "system", "content": "You are an expert coding assistant."},
        {"role": "user", "content": "Refactor the authentication module to use JWT tokens."},
    ]
    result: TurnClassificationResult = turn_guard.classify_turn(messages)
    assert not result.is_tool_loop
    assert not result.is_stagnant
    assert result.target_action == TurnAction.SLM_PLAN
    assert result.tool_call_streak == 0
    assert result.error_streak == 0


def test_turn_guard_active_tool_loop_bypasses_to_active_tier(turn_guard: TurnGuard):
    """In-flight tool response with valid output bypasses SLM directly to active tier."""
    messages = [
        {"role": "user", "content": "Find all usages of resolve_model"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "grep", "arguments": '{"query": "resolve_model"}'},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "grep",
            "content": "autoconduck/orchestrator/runner.py:32: def run_dynamic_orchestration(...)",
        },
    ]
    result = turn_guard.classify_turn(messages)
    assert result.is_tool_loop
    assert not result.is_stagnant
    assert result.target_action == TurnAction.DIRECT_ACTIVE_TIER
    assert result.tool_call_streak >= 1
    assert result.last_tool_name == "grep"
    assert result.error_streak == 0


def test_turn_guard_healthy_loop_across_many_files_stays_active(turn_guard: TurnGuard):
    """Productive tool loops touching many files do not trigger stagnation."""
    messages = [{"role": "user", "content": "Refactor these files"}]
    for index in range(11):
        tool_name = "read" if index % 2 == 0 else "edit"
        call_id = f"call_{index}"
        path = f"src/file_{index}.py"
        messages.extend([
            {
                "role": "assistant",
                "tool_calls": [{
                    "id": call_id,
                    "type": "function",
                    "function": {"name": tool_name, "arguments": json.dumps({"path": path})},
                }],
            },
            {"role": "tool", "tool_call_id": call_id, "name": tool_name, "content": "success"},
        ])

    result = turn_guard.classify_turn(messages)
    assert result.is_tool_loop is True
    assert result.is_stagnant is False
    assert result.target_action == TurnAction.DIRECT_ACTIVE_TIER


def test_turn_guard_stagnation_three_identical_calls_escalates(turn_guard: TurnGuard):
    """3 consecutive identical tool calls trigger stagnation escalation to SLM."""
    call_spec = {
        "id": "call_rep",
        "type": "function",
        "function": {"name": "read_file", "arguments": '{"path": "autoconduck/config.py"}'},
    }
    tool_resp = {
        "role": "tool",
        "tool_call_id": "call_rep",
        "name": "read_file",
        "content": "# config.py content...",
    }

    messages = [
        {"role": "user", "content": "Check config"},
        {"role": "assistant", "tool_calls": [call_spec]},
        tool_resp,
        {"role": "assistant", "tool_calls": [call_spec]},
        tool_resp,
        {"role": "assistant", "tool_calls": [call_spec]},
        tool_resp,
    ]
    result = turn_guard.classify_turn(messages)
    assert result.is_stagnant
    assert result.target_action == TurnAction.ESCALATE_SLM
    assert result.stagnation_reason is not None
    assert "identical" in result.stagnation_reason.lower() or "loop" in result.stagnation_reason.lower()


def test_turn_guard_stagnation_two_consecutive_errors_escalates(turn_guard: TurnGuard):
    """2 consecutive tool execution errors trigger stagnation escalation to SLM."""
    messages = [
        {"role": "user", "content": "Fix the build"},
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "call_e1", "type": "function", "function": {"name": "bash", "arguments": '{"command": "pytest"}'}}
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_e1",
            "name": "bash",
            "content": "Error: Command failed with exit code 1. ModuleNotFoundError: 'foo'",
        },
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "call_e2", "type": "function", "function": {"name": "bash", "arguments": '{"command": "pytest tests/"}'}}
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_e2",
            "name": "bash",
            "content": "FAILED tests/test_foo.py - ModuleNotFoundError: 'foo'",
        },
    ]
    result = turn_guard.classify_turn(messages)
    assert result.is_stagnant
    assert result.target_action == TurnAction.ESCALATE_SLM
    assert result.error_streak >= 2
    assert result.stagnation_reason is not None
    assert "error" in result.stagnation_reason.lower()


def test_turn_guard_streak_counters_reset_on_progress(turn_guard: TurnGuard):
    """A successful tool call resets error streaks and progress is tracked accurately."""
    messages = [
        {"role": "user", "content": "Execute task"},
        {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "bash", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "name": "bash", "content": "Error: command not found"},
        {"role": "assistant", "tool_calls": [{"id": "c2", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "a.py"}'}}]},
        {"role": "tool", "tool_call_id": "c2", "name": "read_file", "content": "def a(): pass"},
    ]
    result = turn_guard.classify_turn(messages)
    assert not result.is_stagnant
    assert result.target_action == TurnAction.DIRECT_ACTIVE_TIER
    assert result.error_streak == 0
    assert result.last_tool_name == "read_file"


# ==============================================================================
# Tier 2: Boundary & Corner Cases (>=5 tests)
# ==============================================================================

def test_turn_guard_empty_messages_list(turn_guard: TurnGuard):
    """Empty message sequence returns safe SLM default without throwing."""
    result = turn_guard.classify_turn([])
    assert isinstance(result, TurnClassificationResult)
    assert not result.is_tool_loop
    assert result.target_action == TurnAction.SLM_PLAN


def test_turn_guard_malformed_tool_call_payload(turn_guard: TurnGuard):
    """Malformed or non-dict tool calls are handled safely without crashing."""
    messages = [
        {"role": "user", "content": "Run tool"},
        {"role": "assistant", "tool_calls": "invalid_string_not_list"},
        {"role": "tool", "content": "Some output"},
    ]
    result = turn_guard.classify_turn(messages)
    assert isinstance(result, TurnClassificationResult)
    assert result.target_action in (TurnAction.SLM_PLAN, TurnAction.DIRECT_ACTIVE_TIER)


def test_turn_guard_sub_2ms_execution_sla(turn_guard: TurnGuard):
    """Classification latency across 200 turns must be strictly sub-2ms per call."""
    messages = [
        {"role": "user", "content": "Grep files"},
        {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "grep", "arguments": '{"q": "x"}'}}]},
        {"role": "tool", "tool_call_id": "c1", "name": "grep", "content": "x = 10"},
    ]
    # Warmup
    turn_guard.classify_turn(messages)

    start = time.perf_counter()
    iterations = 200
    for _ in range(iterations):
        turn_guard.classify_turn(messages)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    avg_ms = elapsed_ms / iterations

    assert avg_ms < 2.0, f"Turn Guard latency {avg_ms:.3f}ms exceeds 2.0ms SLA!"


def test_turn_guard_mixed_success_and_error_sequence(turn_guard: TurnGuard):
    """Alternating error and success tool calls do NOT accumulate to 2 consecutive errors."""
    messages = [
        {"role": "user", "content": "Task"},
        {"role": "assistant", "tool_calls": [{"id": "1", "type": "function", "function": {"name": "t1", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "1", "name": "t1", "content": "Error: failed"},
        {"role": "assistant", "tool_calls": [{"id": "2", "type": "function", "function": {"name": "t2", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "2", "name": "t2", "content": "Success: completed step"},
        {"role": "assistant", "tool_calls": [{"id": "3", "type": "function", "function": {"name": "t3", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "3", "name": "t3", "content": "Error: transient glitch"},
    ]
    result = turn_guard.classify_turn(messages)
    assert not result.is_stagnant
    assert result.error_streak == 1
    assert result.target_action == TurnAction.DIRECT_ACTIVE_TIER


def test_turn_guard_anthropic_format_tool_use_and_tool_result(turn_guard: TurnGuard):
    """Supports Anthropic-style tool_use content blocks and tool_result blocks."""
    messages = [
        {"role": "user", "content": "Edit file"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "I will read the file."},
                {"type": "tool_use", "id": "tu_1", "name": "read_file", "input": {"path": "main.py"}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "tu_1", "content": "print('hello')", "is_error": False}
            ],
        },
    ]
    result = turn_guard.classify_turn(messages)
    assert result.is_tool_loop
    assert not result.is_stagnant
    assert result.target_action == TurnAction.DIRECT_ACTIVE_TIER
    assert result.last_tool_name == "read_file"


def test_turn_guard_system_prompt_only(turn_guard: TurnGuard):
    """System-only prompt safely routes to SLM planner."""
    messages = [{"role": "system", "content": "You are an autonomous assistant."}]
    result = turn_guard.classify_turn(messages)
    assert not result.is_tool_loop
    assert result.target_action == TurnAction.SLM_PLAN


def test_turn_guard_code_file_read_no_false_positive_error(turn_guard: TurnGuard):
    """Reading code files with exception handlers and error keywords does not count as error."""
    code_content_1 = '''
    """Dashboard helper."""
    def run():
        try:
            do_something()
        except FileNotFoundError:
            raise RuntimeError("Textual error: failed to initialize")
    '''
    code_content_2 = '''
    """Tuning module."""
    def show():
        self.query_one("#message", Static).update(f"[red]Error: {exc}[/red]")
        logger.error("Failed to connect")
    '''
    messages = [
        {"role": "user", "content": "Analyze dashboard and tune modules"},
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "read", "arguments": '{"path": "dashboard.py"}'}},
                {"id": "c2", "type": "function", "function": {"name": "read", "arguments": '{"path": "tune.py"}'}},
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "name": "read", "content": code_content_1},
        {"role": "tool", "tool_call_id": "c2", "name": "read", "content": code_content_2},
    ]
    result = turn_guard.classify_turn(messages)
    assert result.is_tool_loop is True
    assert result.is_stagnant is False
    assert result.error_streak == 0
    assert result.target_action == TurnAction.DIRECT_ACTIVE_TIER


def test_turn_guard_anthropic_explicit_is_error_false_overrides_content(turn_guard: TurnGuard):
    """Explicit is_error: false in Anthropic tool_result takes precedence."""
    messages = [
        {"role": "user", "content": "Check logs"},
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "tu_log", "name": "read_file", "input": {"path": "error.log"}},
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tu_log",
                    "content": "Error: something failed with exit code 1",
                    "is_error": False,
                }
            ],
        },
    ]
    result = turn_guard.classify_turn(messages)
    assert result.is_tool_loop is True
    assert result.is_stagnant is False
    assert result.error_streak == 0
    assert result.target_action == TurnAction.DIRECT_ACTIVE_TIER


def test_turn_guard_sliding_window_error_density_escalates(turn_guard: TurnGuard):
    """Oscillating error loops (e.g. 50%+ errors in recent window) escalate to SLM."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": "Investigate bug"}]
    # Interleaved error, success, error, error, success, error
    pattern = [True, False, True, True, False, True]
    for i, is_err in enumerate(pattern):
        cid = f"c_{i}"
        messages.extend([
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": cid, "type": "function", "function": {"name": "read_file", "arguments": json.dumps({"path": f"file_{i}.py"})}}
                ],
            },
            {
                "role": "tool",
                "tool_call_id": cid,
                "name": "read_file",
                "content": f"Error: cannot find the path specified" if is_err else "def foo(): pass",
            },
        ])

    result = turn_guard.classify_turn(messages)
    assert result.is_stagnant is True
    assert result.target_action == TurnAction.ESCALATE_SLM
    assert "error density" in result.stagnation_reason.lower()


def test_turn_guard_recurring_root_target_failure_escalates(turn_guard: TurnGuard):
    """Repeated failures on the same invalid root directory (e.g. autoconductor/...) escalate to SLM."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": "Analyze project"}]
    # Non-consecutive failures on autoconductor/* with successful calls in between
    steps = [
        ("autoconductor/digest.py", True),
        ("autoconduck/session_guard.py", False),
        ("autoconductor/runner.py", True),
        ("autoconduck/slm_planner.py", False),
        ("autoconductor/dynamic_factory.py", True),
    ]
    for i, (path, is_err) in enumerate(steps):
        cid = f"call_{i}"
        messages.extend([
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": cid, "type": "function", "function": {"name": "read_file", "arguments": json.dumps({"path": path})}}
                ],
            },
            {
                "role": "tool",
                "tool_call_id": cid,
                "name": "read_file",
                "content": f"Error: no such file or directory: {path}" if is_err else "# valid code",
            },
        ])

    result = turn_guard.classify_turn(messages)
    assert result.is_stagnant is True
    assert result.target_action == TurnAction.ESCALATE_SLM
    assert "autoconductor" in result.stagnation_reason.lower()


def test_turn_guard_suggests_replan_on_read_heavy_zero_edits(turn_guard: TurnGuard):
    """8+ read calls without any edits suggests a mid-execution replan."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": "Refactor codebase"}]
    for i in range(8):
        cid = f"call_{i}"
        messages.extend([
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": cid, "type": "function", "function": {"name": "read", "arguments": json.dumps({"path": f"src/module_{i}.py"})}}
                ],
            },
            {
                "role": "tool",
                "tool_call_id": cid,
                "name": "read",
                "content": f"# module {i} contents",
            },
        ])

    result = turn_guard.classify_turn(messages)
    assert result.is_tool_loop is True
    assert result.is_stagnant is False
    assert result.target_action == TurnAction.SUGGEST_REPLAN
    assert result.replan_suggested is True
    assert result.read_count >= 8
    assert result.edit_count == 0
    assert "without edits" in (result.replan_reason or "")


def test_turn_guard_does_not_suggest_replan_when_edits_present(turn_guard: TurnGuard):
    """Active tool loop with edits present continues direct active tier without replan suggestion."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": "Refactor codebase"}]
    for i in range(7):
        cid = f"call_read_{i}"
        messages.extend([
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": cid, "type": "function", "function": {"name": "read", "arguments": json.dumps({"path": f"src/module_{i}.py"})}}
                ],
            },
            {
                "role": "tool",
                "tool_call_id": cid,
                "name": "read",
                "content": f"# module {i} contents",
            },
        ])
    # Add an edit call
    cid_edit = "call_edit_0"
    messages.extend([
        {
            "role": "assistant",
            "tool_calls": [
                {"id": cid_edit, "type": "function", "function": {"name": "write_to_file", "arguments": json.dumps({"path": "src/module_0.py"})}}
            ],
        },
        {
            "role": "tool",
            "tool_call_id": cid_edit,
            "name": "write_to_file",
            "content": "ok",
        },
    ])

    result = turn_guard.classify_turn(messages)
    assert result.is_tool_loop is True
    assert result.is_stagnant is False
    assert result.target_action == TurnAction.DIRECT_ACTIVE_TIER
    assert result.replan_suggested is False
    assert result.edit_count == 1



# ==============================================================================
# Tier 4: Regression Tests for OMP Edit Error Escalation & Fan-Out
# ==============================================================================

def test_turn_guard_escalates_on_omp_anchored_edit_errors(turn_guard: TurnGuard):
    """5 consecutive edit failures like in OMP session trigger ESCALATE_SLM."""
    omp_error = 'input must begin with "[PATH#HASH]" on the first non-blank line for anchored edits; got: "*** Update File: autoconduck/stats.py". Example: "[src/foo.ts#1A2B]" then edit ops.'
    messages = [
        {"role": "user", "content": "Rework stats page"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "edit", "arguments": '{"i": "patch 1", "input": "*** Begin Patch"}'},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "edit",
            "content": omp_error,
        },
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {"name": "edit", "arguments": '{"i": "[autoconduck/stats.py#31BD]", "input": "*** Begin Patch"}'},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_2",
            "name": "edit",
            "content": omp_error,
        },
    ]
    result = turn_guard.classify_turn(messages)
    assert result.is_stagnant is True
    assert result.target_action == TurnAction.ESCALATE_SLM
    assert result.error_streak >= 2


def test_turn_guard_escalates_on_toolresult_role_with_is_error_flag(turn_guard: TurnGuard):
    """OMP custom toolResult message format with isError: True triggers escalation on consecutive errors."""
    messages = [
        {"role": "user", "content": "Fix code"},
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "edit", "arguments": '{"path": "a.py"}'}}
            ],
        },
        {
            "role": "toolResult",
            "toolCallId": "c1",
            "toolName": "edit",
            "content": [{"type": "text", "text": "syntax error: unexpected token"}],
            "isError": True,
        },
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "c2", "type": "function", "function": {"name": "edit", "arguments": '{"path": "a.py", "retry": 1}'}}
            ],
        },
        {
            "role": "toolResult",
            "toolCallId": "c2",
            "toolName": "edit",
            "content": [{"type": "text", "text": "syntax error: unexpected token"}],
            "isError": True,
        },
    ]
    result = turn_guard.classify_turn(messages)
    assert result.is_stagnant is True
    assert result.target_action == TurnAction.ESCALATE_SLM


def test_turn_guard_escalates_on_identical_consecutive_error_messages(turn_guard: TurnGuard):
    """Two consecutive tool calls returning the exact same error message trigger ESCALATE_SLM."""
    messages = [
        {"role": "user", "content": "Execute task"},
        {
            "role": "assistant",
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "bash", "arguments": '{"command": "foo"}'}}],
        },
        {"role": "tool", "tool_call_id": "c1", "name": "bash", "content": "the term 'foo' is not recognized as a name of a cmdlet"},
        {
            "role": "assistant",
            "tool_calls": [{"id": "c2", "type": "function", "function": {"name": "bash", "arguments": '{"command": "./foo"}'}}],
        },
        {"role": "tool", "tool_call_id": "c2", "name": "bash", "content": "the term 'foo' is not recognized as a name of a cmdlet"},
    ]
    result = turn_guard.classify_turn(messages)
    assert result.is_stagnant is True
    assert result.target_action == TurnAction.ESCALATE_SLM


def test_harness_fan_out_plan_generates_agent_assignments():
    """Harness fan-out coordinator properly assigns Agent 1, Agent 2... with directives."""
    from autoconduck.orchestrator.fan_out import build_harness_fan_out_plan
    from autoconduck.routing.slm_planner import ExecutionPlan, SubTaskSpec, CapabilitySLA

    plan = ExecutionPlan(
        route="dynamic_dag",
        confidence=0.9,
        task_type="multi_edit",
        suggested_sla=CapabilitySLA(min_context=16000),
        synthesizer_sla=CapabilitySLA(requires_reasoning=True),
        needs_rag=False,
        rag_queries=[],
        subtasks=[
            SubTaskSpec(id="recon", goal="Analyze stats UI architecture", role="recon", scope=["autoconduck/stats.py"]),
            SubTaskSpec(id="read", goal="Read target files", role="read", depends_on=["recon"], scope=["tests/"]),
            SubTaskSpec(id="edit", goal="Apply patch", role="edit", depends_on=["read"], scope=["autoconduck/stats.py"]),
        ],
    )

    fan_out = build_harness_fan_out_plan(plan, max_subagents=4)
    assert fan_out.can_fan_out is True
    assert len(fan_out.sequential_fallback) == 3
    assert fan_out.sequential_fallback[0].agent_label == "Agent 1"
    assert fan_out.sequential_fallback[1].agent_label == "Agent 2"
    assert fan_out.sequential_fallback[2].agent_label == "Agent 3"
    assert any("Agent 1" in d for d in fan_out.fan_out_directives)


def test_render_plan_summary_for_user():
    """User-visible plan renderer formats agent fan-out assignments."""
    from autoconduck.orchestrator.handoff import render_plan_summary_for_user
    from autoconduck.routing.slm_planner import ExecutionPlan, SubTaskSpec, CapabilitySLA

    plan = ExecutionPlan(
        route="dynamic_dag",
        confidence=0.95,
        task_type="refactor",
        suggested_sla=CapabilitySLA(min_context=16000),
        synthesizer_sla=CapabilitySLA(requires_reasoning=True),
        needs_rag=False,
        rag_queries=[],
        subtasks=[
            SubTaskSpec(id="task_1", goal="Inspect architecture", role="recon"),
            SubTaskSpec(id="task_2", goal="Implement code changes", role="edit"),
        ],
    )

    summary = render_plan_summary_for_user(plan)
    assert "SYNTHESIZED EXECUTION PLAN & AGENT ASSIGNMENTS" in summary
    assert "Agent 1" in summary
    assert "Agent 2" in summary
    assert "Inspect architecture" in summary


def test_topological_batching_and_tool_templates():
    """Topological batching groups independent tasks into parallel Batch 1 and dependent tasks into Batch 2."""
    from autoconduck.orchestrator.fan_out import build_harness_fan_out_plan
    from autoconduck.routing.slm_planner import ExecutionPlan, SubTaskSpec, CapabilitySLA

    plan = ExecutionPlan(
        route="dynamic_dag",
        confidence=0.95,
        task_type="refactor",
        suggested_sla=CapabilitySLA(min_context=16000),
        synthesizer_sla=CapabilitySLA(requires_reasoning=True),
        needs_rag=False,
        rag_queries=[],
        subtasks=[
            SubTaskSpec(id="recon_1", goal="Inspect frontend UI", role="recon", scope=["ui/"]),
            SubTaskSpec(id="recon_2", goal="Inspect backend API", role="recon", scope=["api/"]),
            SubTaskSpec(id="edit_1", goal="Implement changes", role="edit", depends_on=["recon_1", "recon_2"], scope=["src/"]),
        ],
    )

    # Test Claude Code tool template
    claude_fan_out = build_harness_fan_out_plan(plan, max_subagents=4, client_type="claude")
    assert claude_fan_out.can_fan_out is True
    assert len(claude_fan_out.batches) == 2
    assert claude_fan_out.batches[0].mode == "parallel"
    assert len(claude_fan_out.batches[0].agents) == 2
    assert claude_fan_out.batches[1].mode == "sequential"
    assert len(claude_fan_out.batches[1].agents) == 1
    assert "Task(" in claude_fan_out.batches[0].agents[0].tool_call_template

    # Test OMP tool template
    omp_fan_out = build_harness_fan_out_plan(plan, max_subagents=4, client_type="omp")
    assert "task(" in omp_fan_out.batches[0].agents[0].tool_call_template

    # Test contract dict
    contract_dict = claude_fan_out.to_contract_dict()
    assert contract_dict["supported"] is True
    assert len(contract_dict["batches"]) == 2
    assert contract_dict["batches"][0]["mode"] == "parallel"


def test_session_execution_contract_includes_fan_out():
    """format_execution_handoff embeds fan_out data in Session Execution Contract JSON."""
    import json
    from autoconduck.orchestrator.handoff import format_execution_handoff
    from autoconduck.routing.slm_planner import ExecutionPlan, SubTaskSpec

    plan = ExecutionPlan(
        route="dynamic_dag",
        confidence=0.9,
        task_type="refactor",
        subtasks=[
            SubTaskSpec(id="t1", goal="Explore", role="recon"),
            SubTaskSpec(id="t2", goal="Analyze", role="recon"),
            SubTaskSpec(id="t3", goal="Patch", role="edit", depends_on=["t1", "t2"]),
        ],
    )
    handoff = format_execution_handoff(plan, {}, "", client_type="claude")
    assert "### Session Execution Contract" in handoff
    json_marker = "```json\n"
    json_start = handoff.find(json_marker) + len(json_marker)
    json_end = handoff.find("\n```", json_start)
    contract = json.loads(handoff[json_start:json_end])
    assert contract["schema_version"] == "0.4"
    assert "fan_out" in contract
    assert contract["fan_out"]["supported"] is True
    assert len(contract["fan_out"]["batches"]) == 2
