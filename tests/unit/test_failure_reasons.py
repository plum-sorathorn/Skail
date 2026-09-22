"""Failing-first regression: failure events must carry a redacted reason."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import ToolMessage

from skail.tools.assembly import RuntimeActivityMiddleware


def _request(name: str, call_id: str) -> Any:
    from langchain.agents.middleware import ToolCallRequest

    return ToolCallRequest(
        tool_call={"name": name, "id": call_id, "args": {}, "type": "tool_call"},
        tool=None,
        state={},
        runtime=None,  # type: ignore[arg-type]
    )


def _middleware(captured: list[tuple[tuple[Any, ...], dict[str, Any]]]) -> Any:
    def _emit(*args: Any, **kwargs: Any) -> None:
        captured.append((args, kwargs))

    return RuntimeActivityMiddleware(model_name="m", emit=_emit, redactor=None)


def test_tool_failed_carries_reason() -> None:
    captured: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    middleware = _middleware(captured)

    def tool_error(request: Any) -> ToolMessage:
        return ToolMessage(
            content="disk write failed",
            tool_call_id=request.tool_call["id"],
            status="error",
        )

    middleware._run_tool(_request("edit_file", "call-1"), tool_error)
    failed = [c for c in captured if c[0] and c[0][0] == "tool.failed"]
    assert failed, "expected a tool.failed emission"
    args, kwargs = failed[0]
    reason = kwargs.get("reason") if len(args) < 3 else args[2]
    assert reason is not None and "disk write failed" in str(reason)


def test_tool_failed_validation_carries_hint() -> None:
    captured: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    middleware = _middleware(captured)

    def _boom(request: Any) -> ToolMessage:  # pragma: no cover - must not run
        raise AssertionError("handler must not run on validation failure")

    # grep with an invalid arg type triggers the validation-hint path.
    middleware._run_tool(
        _request("grep", "call-hint"),
        _boom,  # type: ignore[arg-type]
    )
    failed = [c for c in captured if c[0] and c[0][0] == "tool.failed"]
    assert failed, "expected a tool.failed emission"
    args, kwargs = failed[0]
    reason = kwargs.get("reason") if len(args) < 3 else args[2]
    assert reason is not None and str(reason).strip() != ""
