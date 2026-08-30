"""Plugin sandbox for salvaged executor loop + tools (Phase 1B). Not yet wired."""

from autoconduck.plugin.executor_loop import (
    LoopState,
    calculate_stagnation,
    extract_text_tool_calls,
    run_executor_tool_loop,
    strip_tool_call_tags,
)
from autoconduck.plugin.tools import (
    TOOL_SCHEMAS,
    execute_tool,
    is_read_only_tool,
    tool_model,
)

__all__ = [
    "LoopState",
    "calculate_stagnation",
    "extract_text_tool_calls",
    "run_executor_tool_loop",
    "strip_tool_call_tags",
    "TOOL_SCHEMAS",
    "execute_tool",
    "is_read_only_tool",
    "tool_model",
]
