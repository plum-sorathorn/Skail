"""D-5: messages-channel producer invariant contract.

Pins every known production construction of the ``{"messages": [...]}``
channel (site noted per case) to the ``list[BaseMessage]`` invariant so the
historical "Message as a sequence must be (role, template)" failure (D-5)
cannot silently regress. The failure dump itself is pinned by
``tests/unit/test_run_controller_diagnostics.py``; this contract rejects any
producer drifting away from a BaseMessage sequence.

Recorded decision: D-5 is unreproducible/monitored and pinned to the
installed ``langchain_core`` version; see
``docs/decisions/0002-framework-version-contract.md``. Reopen on a second
occurrence.
"""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from skail.domain.ids import TaskId
from skail.domain.tasks import TaskResult

# Known messages-channel producers in src/skail:
# - lead invoke            (src/skail/runtime/run_controller.py:2121)
# - checkpoint re-invoke   (src/skail/runtime/run_controller.py:1291)
# - plan subagent dispatch (src/skail/runtime/run_controller.py:1354)
# - child invoke           (src/skail/runtime/run_controller.py:3243)
# - resume fallback        (src/skail/runtime/run_controller.py:2736)
# - task_graph result      (src/skail/agents/task_graph.py:506-517)
PRODUCERS = (
    "lead_invoke",
    "checkpoint_re_invoke",
    "plan_subagent_dispatch",
    "child_invoke",
    "resume_fallback",
    "task_graph_result",
)


@pytest.mark.parametrize("producer", PRODUCERS)
def test_producer_yields_base_message_sequence(producer: str) -> None:
    messages = _produce(producer)["messages"]

    assert isinstance(messages, list)
    assert all(isinstance(message, BaseMessage) for message in messages)


def _produce(producer: str) -> dict[str, list[BaseMessage]]:
    if producer == "lead_invoke":
        # run_controller.py:2121-2123: {"messages": [HumanMessage(instruction)]}
        instruction = "do the thing"
        return {"messages": [HumanMessage(content=instruction)]}
    if producer == "checkpoint_re_invoke":
        # run_controller.py:1291-1300: the stored checkpoint payload replays
        # into the lead as a single SystemMessage.
        checkpoint_payload = {"attempt_id": "attempt-1", "keys": ["run"]}
        return {
            "messages": [
                SystemMessage(
                    content=json.dumps(
                        checkpoint_payload,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
            ]
        }
    if producer == "plan_subagent_dispatch":
        # run_controller.py:1354: dispatch.spec.request.description.
        return {"messages": [HumanMessage(content="planned node description")]}
    if producer == "child_invoke":
        # run_controller.py:3243: the formatted context packet.
        return {"messages": [HumanMessage(content="formatted prompt")]}
    if producer == "resume_fallback":
        # run_controller.py:2736: recovery without a stored lead state.
        return {"messages": []}
    if producer == "task_graph_result":
        # task_graph.py:506-517: the TaskResult publishes as AIMessage(json).
        result = TaskResult(
            task_id=TaskId("33333333-3333-4333-8333-333333333333"),
            status="blocked",
            summary="Task validation rejected: unknown_profile",
        )
        return {"messages": [AIMessage(content=result.model_dump_json())]}
    raise AssertionError(f"unknown messages-channel producer: {producer}")
