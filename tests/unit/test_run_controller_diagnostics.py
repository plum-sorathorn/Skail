import pytest
from langchain_core.messages import HumanMessage

from skail.runtime.run_controller import (
    _collect_message_sequence_diagnostics,
    _is_message_sequence_error,
)

_MESSAGE_SEQUENCE_ERROR = NotImplementedError(
    "Message as a sequence must be (role string, template)"
)


class _FabricatedState:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = values


class _FabricatedLeadAgent:
    def __init__(self, values: dict[str, object] | None) -> None:
        self._values = values

    async def aget_state(self, config: object) -> _FabricatedState:
        if self._values is None:
            raise RuntimeError("state unavailable")
        return _FabricatedState(self._values)


@pytest.mark.asyncio
async def test_message_sequence_failure_produces_read_only_shape_dump() -> None:
    assert _is_message_sequence_error(_MESSAGE_SEQUENCE_ERROR) is True
    wrapped = RuntimeError("lead invocation failed")
    wrapped.__cause__ = _MESSAGE_SEQUENCE_ERROR
    assert _is_message_sequence_error(wrapped) is True
    assert _is_message_sequence_error(RuntimeError("boom")) is False

    lead_agent = _FabricatedLeadAgent({"messages": [("only-one",), ("role", "template")]})

    shapes = await _collect_message_sequence_diagnostics(lead_agent, {"configurable": {}})

    assert "0:tuple(len=1,first=str)" in shapes
    assert "1:tuple(len=2,first=str)" in shapes


@pytest.mark.asyncio
async def test_shape_dump_guards_against_diagnostics_failures() -> None:
    lead_agent = _FabricatedLeadAgent(None)

    shapes = await _collect_message_sequence_diagnostics(lead_agent, {})

    assert shapes == "message-shape diagnostics unavailable"


@pytest.mark.asyncio
async def test_failure_dump_reports_element_type_and_length_per_element() -> None:
    lead_agent = _FabricatedLeadAgent(
        {
            "messages": [
                HumanMessage(content="hello"),
                ("role", "template"),
                "plain",
                42,
            ]
        }
    )

    shapes = await _collect_message_sequence_diagnostics(lead_agent, {"configurable": {}})

    assert "messages[4]=[" in shapes
    assert "0:HumanMessage" in shapes
    assert "1:tuple(len=2,first=str)" in shapes
    assert "2:str" in shapes
    assert "3:int" in shapes
