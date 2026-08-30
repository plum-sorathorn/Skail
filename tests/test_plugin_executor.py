"""Plugin executor loop + tools tests (salvaged from orchestrator, Phase 1B)."""
import json
import pytest
from unittest.mock import MagicMock, patch

from autoconduck.config import Config, SelectionConfig

from autoconduck.plugin.executor_loop import (
    LoopState,
    calculate_stagnation,
    extract_text_tool_calls,
    strip_tool_call_tags,
    run_executor_tool_loop,
)
from autoconduck.plugin.tools import is_read_only_tool, tool_model


def test_extract_text_tool_calls_opensource_format():
    sample = (
        "I understand. Let me check the files first.<tool_calls:opensource>\n"
        "<tool_call:opensource>read<tool_sep:opensource>\n"
        "<arg_key:opensource>path</arg_key:opensource>\n"
        "<arg_value:opensource>autoconduck/subagents.py</arg_value:opensource>\n"
        "</tool_call:opensource>\n"
        "<tool_call:opensource>read<tool_sep:opensource>\n"
        "<arg_key:opensource>path</arg_key:opensource>\n"
        "<arg_value:opensource>autoconduck/tools.py</arg_value:opensource>\n"
        "</tool_call:opensource>"
    )
    calls = extract_text_tool_calls(sample)
    assert len(calls) == 2
    assert calls[0]["function"]["name"] == "read"
    assert json.loads(calls[0]["function"]["arguments"]) == {"path": "autoconduck/subagents.py"}
    assert calls[1]["function"]["name"] == "read"
    assert json.loads(calls[1]["function"]["arguments"]) == {"path": "autoconduck/tools.py"}

    cleaned = strip_tool_call_tags(sample)
    assert "I understand. Let me check the files first." in cleaned
    assert "<tool_calls:opensource>" not in cleaned


def test_extract_text_tool_calls_generic_json():
    sample = '<tool_call>{"name": "grep", "arguments": {"pattern": "def score"}}</tool_call>'
    calls = extract_text_tool_calls(sample)
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "grep"
    assert json.loads(calls[0]["function"]["arguments"]) == {"pattern": "def score"}

    cleaned = strip_tool_call_tags(sample)
    assert cleaned == ""


def test_read_only_tools_are_routed_to_fast_model():
    cfg = Config(
        model_list=[
            {"id": "cheap", "price_in": 0.1, "price_out": 0.1, "enabled": True},
            {"id": "pricey", "price_in": 2.0, "price_out": 5.0, "enabled": True},
        ]
    )
    assert is_read_only_tool("read")
    assert is_read_only_tool("grep")
    assert tool_model("read", "pricey", cfg) == "cheap"
    assert tool_model("edit", "pricey", cfg) == "pricey"


@pytest.mark.asyncio
async def test_executor_stagnation_injects_mitigation_note(tmp_path):
    class FakeClient:
        def __init__(self):
            self.messages = []

        def completion(self, *, messages, **kwargs):
            self.messages.append((messages, kwargs))
            return {"choices": [{"message": {"content": "", "tool_calls": [{
                "id": str(len(self.messages)), "function": {
                    "name": "read", "arguments": '{"path":"missing.py"}'
                }
            }]}}]}

    client = FakeClient()
    cfg = Config(model_list=[
        {"id": "cheap", "price_in": 0.1, "price_out": 0.1, "enabled": True},
        {"id": "pricey", "price_in": 2.0, "price_out": 5.0, "enabled": True},
    ])
    result = await run_executor_tool_loop(client, "pricey", "system", "user",
        allowed_scope=["missing.py"], workspace_root=tmp_path, cfg=cfg,
        max_rounds=4, tool_retry_cap=10)
    assert isinstance(result, str)
    assert any("<loop-stagnation:true>" in str(message.get("content", ""))
               for messages, _ in client.messages for message in messages)
    assert any(kwargs.get("model") == "openai/cheap"
               for _, kwargs in client.messages[3:])

    state = LoopState(
        call_signatures=["same", "same", "same"],
        error_streak=3,
        distinct_files_touched={"missing.py"},
        total_calls=3,
    )
    assert calculate_stagnation(state) > 0.70


def test_calculate_stagnation_basic():
    s = LoopState(call_signatures=["a", "b", "c"], error_streak=0, distinct_files_touched={"a.py", "b.py"}, total_calls=3)
    assert 0 <= calculate_stagnation(s) <= 1
    s2 = LoopState(call_signatures=["same", "same", "same"], error_streak=3, distinct_files_touched=set(), total_calls=3)
    assert calculate_stagnation(s2) > calculate_stagnation(s)
