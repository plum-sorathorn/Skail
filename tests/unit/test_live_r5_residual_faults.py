"""Offline regression repros for the two residual live faults (R5 follow-up).

No live calls, no secrets. ScriptedChatModel drives the REAL
ExecutionDecisionGate / ExecutionDecisionMiddleware /
RuntimeActivityMiddleware / TaskBoundModelMiddleware.

Fault A (P5 no-op): a run completes with every tool failed and zero
children. Hypothesis under test: the mini model emits malformed plan
shapes, the gate burns its repairs on ``plan_invalid`` and then
locks at ``repair_exhausted``, so nothing is ever admitted and every
operational tool (grep/glob/read/task) is gated.

Fault B (P6/P7 ReadTimeout): a single slow no-tool model call raises
httpx.ReadTimeout inside the model-call handler.
"""

# mypy: disable-error-code="import-untyped"
from __future__ import annotations

from typing import Any, cast

import httpx
import pytest
from langchain.agents.middleware import ModelRequest, ModelResponse, ToolCallRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from skail.config.models import ProviderConfig
from skail.providers.base import ModelOptions
from skail.providers.errors import ProviderErrorKind
from skail.providers.fallback import ProviderFallbackPolicy
from skail.providers.openai_compatible import OpenAICompatibleAdapter
from skail.routing.assignment import AccountingReconciliationRequired
from skail.runtime.decisions import (
    DecisionAdmissionError,
    ExecutionDecisionGate,
    ExecutionDecisionMiddleware,
)
from skail.runtime.model_middleware import TaskBoundModelMiddleware
from skail.runtime.redaction import RedactionRegistry
from skail.tools.assembly import RuntimeActivityMiddleware, normalize_tool_args
from tests.fakes.models import ScriptedChatModel

# ---------------------------------------------------------------------------
# Fault A fixtures
# ---------------------------------------------------------------------------

#: A planned decision whose plan shape a small model plausibly emits: the
#: node is missing its required ``objective`` field, so pydantic validation
#: fails and the gate reports ``decision.plan_invalid``.
MALFORMED_PLAN_ARGS: dict[str, Any] = {
    "mode": "planned",
    "objective": "migrate the thing",
    "reason": "live fire",
    "constraints": (),
    "plan": {
        "schema_version": 1,
        "policy_version": "adaptive-v1",
        "revision": 1,
        "nodes": [{"local_id": "n1", "kind": "tool"}],
    },
    "revision": None,
}

VALID_PLAN_ARGS: dict[str, Any] = {
    "mode": "planned",
    "objective": "survey the repo",
    "reason": "recon",
    "constraints": (),
    "plan": {
        "schema_version": 1,
        "policy_version": "adaptive-v1",
        "revision": 1,
        "nodes": [
            {
                "local_id": "explore",
                "kind": "checkpoint",
                "objective": "survey the repo",
                "effect_scope": "read",
            }
        ],
    },
    "revision": None,
}


def _p5_gate() -> tuple[ExecutionDecisionGate, list[Any]]:
    admitted: list[Any] = []
    return ExecutionDecisionGate(admit_plan=admitted.append), admitted


def _tool_request(name: str, args: dict[str, Any], call_id: str) -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"name": name, "args": args, "id": call_id, "type": "tool_call"},
        tool=None,
        state=None,
        runtime=None,  # type: ignore[arg-type]  # harness only touches tool_call
    )


async def _ok_terminal(spawned: list[str], request: ToolCallRequest) -> ToolMessage:
    spawned.append(str(request.tool_call["name"]))
    call_id = request.tool_call.get("id")
    assert isinstance(call_id, str)
    return ToolMessage(content="child spawned", tool_call_id=call_id)


def test_a1_first_malformed_planned_decision_rejected_plan_invalid() -> None:
    gate, _ = _p5_gate()
    with pytest.raises(DecisionAdmissionError, match="decision.plan_invalid"):
        gate.admit(dict(MALFORMED_PLAN_ARGS))
    assert gate.decision is None
    assert gate.repairs_remaining == 1


def test_a2_second_malformed_decision_raises_repair_exhausted() -> None:
    gate, _ = _p5_gate()
    with pytest.raises(DecisionAdmissionError, match="decision.plan_invalid"):
        gate.admit(dict(MALFORMED_PLAN_ARGS))
    with pytest.raises(DecisionAdmissionError, match="decision.plan_invalid"):
        gate.admit(dict(MALFORMED_PLAN_ARGS))
    with pytest.raises(DecisionAdmissionError, match="decision.repair_exhausted"):
        gate.admit(dict(MALFORMED_PLAN_ARGS))
    assert gate.decision is None
    assert gate.repairs_remaining == 0


def test_a1_rejection_is_actionable_with_missing_fields_and_skeleton() -> None:
    gate, _ = _p5_gate()
    with pytest.raises(DecisionAdmissionError) as caught:
        gate.admit(dict(MALFORMED_PLAN_ARGS))
    message = str(caught.value)
    assert message.startswith("decision.plan_invalid")
    assert "plan.nodes.0.objective" in message
    assert "schema_version" in message


async def test_a3_gated_run_completes_with_every_tool_failed() -> None:
    """Reproduces the live P5 signature: 3 failed execution_decision calls,
    then grep x3 / glob x1 / read_file x4 / task x3 all gated, zero children,
    and no exception escapes (the run "completes")."""
    gate, _ = _p5_gate()
    middleware = ExecutionDecisionMiddleware(gate)
    with pytest.raises(DecisionAdmissionError, match="plan_invalid"):
        gate.admit(dict(MALFORMED_PLAN_ARGS))
    with pytest.raises(DecisionAdmissionError, match="plan_invalid"):
        gate.admit(dict(MALFORMED_PLAN_ARGS))
    with pytest.raises(DecisionAdmissionError, match="repair_exhausted"):
        gate.admit(dict(MALFORMED_PLAN_ARGS))
    assert gate.is_exhausted

    spawned: list[str] = []

    async def terminal(request: ToolCallRequest) -> ToolMessage:
        return await _ok_terminal(spawned, request)

    fan_out: list[tuple[str, dict[str, Any]]] = (
        [("grep", {"pattern": "TODO", "path": "."})] * 3
        + [("glob", {"pattern": "**/*.py"})]
        + [("read_file", {"file_path": "pyproject.toml"})] * 4
        + [("task", {"description": "explore", "prompt": "survey"})] * 3
    )
    results: list[str] = []
    for index, (name, args) in enumerate(fan_out):
        result = await middleware.awrap_tool_call(
            _tool_request(name, args, f"call-{index}"), terminal
        )
        assert isinstance(result, ToolMessage)
        results.append(str(result.content))
    assert spawned == []
    assert len(results) == 11
    assert all(
        content.startswith("execution.decision_exhausted") for content in results
    )


async def test_a3b_exhausted_rejections_count_as_monitor_errors_not_blocked() -> None:
    """Terminal-lock probe: once repairs are spent with no decision, gated
    op-tool rejections flow to the monitor as errors (blocked=False) so the
    run fails loudly instead of completing 0/14 silently."""
    from skail.runtime.failure_monitor import FailureMonitor
    from skail.tools.assembly import RuntimeActivityMiddleware

    gate, _ = _p5_gate()
    with pytest.raises(DecisionAdmissionError, match="plan_invalid"):
        gate.admit(dict(MALFORMED_PLAN_ARGS))
    with pytest.raises(DecisionAdmissionError, match="plan_invalid"):
        gate.admit(dict(MALFORMED_PLAN_ARGS))
    with pytest.raises(DecisionAdmissionError, match="repair_exhausted"):
        gate.admit(dict(MALFORMED_PLAN_ARGS))
    assert gate.is_exhausted

    events: list[tuple[str, str]] = []
    activity = RuntimeActivityMiddleware(
        model_name="mini",
        emit=lambda kind, name: events.append((kind, name)),
        redactor=RedactionRegistry(),
    )
    decision_middleware = ExecutionDecisionMiddleware(gate)

    async def terminal(request: ToolCallRequest) -> Any:
        call_id = request.tool_call.get("id")
        assert isinstance(call_id, str)
        return ToolMessage(content="ok", tool_call_id=call_id)

    async def via_decision(request: ToolCallRequest) -> Any:
        return await decision_middleware.awrap_tool_call(request, terminal)

    with pytest.raises(RuntimeError, match="failure."):
        for index in range(2):
            await activity.awrap_tool_call(
                _tool_request("grep", {"pattern": "TODO", "path": "."}, f"x-{index}"),
                via_decision,
            )
    monitor: FailureMonitor = activity.monitor
    assert monitor._consecutive_errors >= 2  # noqa: SLF001


async def test_a4_wellformed_read_grep_glob_args_stay_gated_without_decision() -> None:
    """Rules out hypothesis 2: read/grep/glob normalize+schema accepts the
    live-style args, so the failures come from the gate, not validation."""
    gate, _ = _p5_gate()
    events: list[tuple[str, str]] = []
    activity = RuntimeActivityMiddleware(
        model_name="mini",
        emit=lambda kind, name: events.append((kind, name)),
        redactor=RedactionRegistry(),
    )
    decision_middleware = ExecutionDecisionMiddleware(gate)

    async def terminal(request: ToolCallRequest) -> ToolMessage:
        call_id = request.tool_call.get("id")
        assert isinstance(call_id, str)
        return ToolMessage(content="ok", tool_call_id=call_id)

    async def via_decision(request: ToolCallRequest) -> Any:
        return await decision_middleware.awrap_tool_call(request, terminal)

    assert normalize_tool_args("grep", {"pattern": "TODO", "path": "."}) == {
        "pattern": "TODO",
        "path": ".",
    }
    assert normalize_tool_args("read_file", {"file_path": "pyproject.toml"}) == {
        "file_path": "pyproject.toml"
    }
    result = await activity.awrap_tool_call(
        _tool_request("grep", {"pattern": "TODO", "path": "."}, "grep-1"),
        via_decision,
    )
    assert isinstance(result, ToolMessage)
    assert str(result.content).startswith("execution.decision_required")


async def test_a5_task_passes_gate_once_valid_decision_admitted() -> None:
    """Rules out hypothesis 3: task routing itself is fine once a decision
    is admitted, so the live zero-children outcome is gate-caused."""
    gate, admitted = _p5_gate()
    gate.admit(dict(VALID_PLAN_ARGS))
    assert gate.decision is not None
    assert admitted
    middleware = ExecutionDecisionMiddleware(gate)
    spawned: list[str] = []

    async def terminal(request: ToolCallRequest) -> ToolMessage:
        return await _ok_terminal(spawned, request)

    result = await middleware.awrap_tool_call(
        _tool_request(
            "task", {"description": "explore", "prompt": "survey"}, "task-1"
        ),
        terminal,
    )
    assert spawned == ["task"]
    assert isinstance(result, ToolMessage)
    assert str(result.content) == "child spawned"


async def test_a6_task_spawns_child_after_p5_malformed_sequence() -> None:
    """Fault A resolved: the actionable plan_invalid lets a scripted model
    correct its plan on repair, so the task tool spawns a child."""
    gate, _ = _p5_gate()
    with pytest.raises(DecisionAdmissionError) as first:
        gate.admit(dict(MALFORMED_PLAN_ARGS))
    assert str(first.value).startswith("decision.plan_invalid")
    assert "plan.nodes.0.objective" in str(first.value)
    # Scripted model corrects on repair using the actionable message.
    gate.admit(dict(VALID_PLAN_ARGS))
    assert gate.decision is not None
    middleware = ExecutionDecisionMiddleware(gate)
    spawned: list[str] = []

    async def terminal(request: ToolCallRequest) -> ToolMessage:
        return await _ok_terminal(spawned, request)

    await middleware.awrap_tool_call(
        _tool_request(
            "task", {"description": "explore", "prompt": "survey"}, "task-1"
        ),
        terminal,
    )
    assert spawned == ["task"], (
        "expected the task tool to spawn a child; the gate admitted nothing "
        f"so every op tool stays decision_required (spawned={spawned!r})"
    )


# ---------------------------------------------------------------------------
# Fault B fixtures / tests
# ---------------------------------------------------------------------------


def _llmgateway_adapter(**kwargs: Any) -> OpenAICompatibleAdapter:
    config = ProviderConfig(
        type="openai-compatible",
        base_url="https://example.test/v1",
        api_key_env="SKAIL_TEST_KEY",
        models=("gpt-5-nano",),
    )
    return OpenAICompatibleAdapter(
        "llmgateway", config, api_key="test-key", **kwargs
    )


async def test_b1_handler_readtimeout_with_call_id_marks_ambiguous_and_holds() -> None:
    """Accounting path (expected to PASS): a handler-raised ReadTimeout with
    a started call_id is marked ambiguous and paid execution is held."""
    ambiguous: list[tuple[str, Exception]] = []
    model = ScriptedChatModel(responses=[AIMessage(content="done")])
    middleware = TaskBoundModelMiddleware(
        models={"nano": model},
        assignments={"assign-1": "nano"},
        call_begin=lambda assignment_id, execution_key: "call-1",
        call_ambiguous=lambda call_id, error: ambiguous.append((call_id, error)),
    )
    request = ModelRequest(
        model=model,
        messages=[HumanMessage(content="hello")],
        state=cast(
            Any,
            {
                "attempt_id": "attempt-1",
                "current_assignment_id": "assign-1",
                "locked_assignment_id": "assign-1",
                "assigned_model": "nano",
            },
        ),
    )

    async def slow_first_token(
        bound: ModelRequest[Any],
    ) -> ModelResponse[Any]:
        raise httpx.ReadTimeout("slow first token")

    with pytest.raises(AccountingReconciliationRequired):
        await middleware.awrap_model_call(request, slow_first_token)
    assert len(ambiguous) == 1
    call_id, error = ambiguous[0]
    assert call_id == "call-1"
    assert isinstance(error, httpx.ReadTimeout)
    assert type(error).__name__ == "ReadTimeout"


def test_b2_model_options_timeout_defaults_to_none() -> None:
    assert ModelOptions().timeout is None


async def test_b3_adapter_request_sets_explicit_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fault B (transport): the provider client is built with an explicit
    httpx timeout (code-controlled, not the httpx default)."""
    captured: dict[str, Any] = {}

    class RecordingClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured.update(kwargs)

        async def __aenter__(self) -> RecordingClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def request(self, *args: Any, **kwargs: Any) -> httpx.Response:
            return httpx.Response(
                200,
                request=httpx.Request(
                    "POST", "https://example.test/v1/chat/completions"
                ),
            )

    monkeypatch.setattr(httpx, "AsyncClient", RecordingClient)
    adapter = _llmgateway_adapter()
    await adapter.request("POST", "/chat/completions", json={"model": "gpt-5-nano"})
    assert "timeout" in captured
    timeout = captured["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert (timeout.connect, timeout.read, timeout.write, timeout.pool) == (
        10.0,
        60.0,
        10.0,
        10.0,
    )


async def test_b3b_model_options_timeout_threads_into_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class RecordingClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured.update(kwargs)

        async def __aenter__(self) -> RecordingClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def request(self, *args: Any, **kwargs: Any) -> httpx.Response:
            return httpx.Response(
                200,
                request=httpx.Request(
                    "POST", "https://example.test/v1/chat/completions"
                ),
            )

    monkeypatch.setattr(httpx, "AsyncClient", RecordingClient)
    adapter = _llmgateway_adapter()
    await adapter.request(
        "POST", "/chat/completions", json={"model": "gpt-5-nano"}, timeout=7.5
    )
    timeout = captured["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.read == 7.5


async def test_b4_adapter_retries_transient_readtimeout() -> None:
    """Fault B (retry): a transient ReadTimeout on the first attempt is
    retried once (2 attempts total, no sleep)."""
    attempts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(str(request.url))
        if len(attempts) == 1:
            raise httpx.ReadTimeout("slow first token")
        return httpx.Response(200, json={"ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        adapter = _llmgateway_adapter(http_async_client=client)
        response = await adapter.request(
            "POST", "/chat/completions", json={"model": "gpt-5-nano"}
        )
    finally:
        await client.aclose()
    assert len(attempts) == 2
    assert response.status_code == 200


async def test_b4b_adapter_retry_gives_up_after_two_attempts() -> None:
    attempts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(str(request.url))
        raise httpx.ReadTimeout("still slow")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        adapter = _llmgateway_adapter(http_async_client=client)
        with pytest.raises(httpx.ReadTimeout):
            await adapter.request(
                "POST", "/chat/completions", json={"model": "gpt-5-nano"}
            )
    finally:
        await client.aclose()
    assert len(attempts) == 2


def test_b5_readtimeout_classified_transient_but_has_no_automatic_retry() -> None:
    """Documents the gap: ReadTimeout is classified retry_safe, yet with no
    fallback equivalents configured nothing ever retries it."""
    adapter = _llmgateway_adapter()
    classified = adapter.classify_error(httpx.ReadTimeout("slow first token"))
    assert classified.kind is ProviderErrorKind.TRANSIENT
    assert classified.retry_safe is True
    policy = ProviderFallbackPolicy({}, is_persisted=lambda binding: True)
    assert (
        policy.fallback_for(
            provider="llmgateway",
            model="gpt-5-nano",
            assignment_id="assign-1",
            error=classified,
        )
        is None
    )
