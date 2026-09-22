"""Coding agent harnesses and tool integration adapters.

Skail connects to coding agent harnesses (Claude Code, OpenCode, Pi).
"""

from __future__ import annotations

from .base import BaseAdapter, GenericAdapter
from .claude_code import ClaudeCodeAdapter
from .opencode import OpenCodeAdapter
from .pi import PiAdapter
from .omp import OmpAdapter

__all__ = [
    "BaseAdapter",
    "GenericAdapter",
    "ClaudeCodeAdapter",
    "OpenCodeAdapter",
    "PiAdapter",
    "OmpAdapter",
    "all_adapters",
    "all_harnesses",
    "binary_name_for",
    "resolve_adapter_for_request",
]


def all_adapters() -> list[BaseAdapter]:
    """Return instances of all supported coding harnesses/adapters."""
    return [
        ClaudeCodeAdapter(),
        OpenCodeAdapter(),
        PiAdapter(),
        OmpAdapter(),
    ]


all_harnesses = all_adapters


def binary_name_for(agent_id: str) -> str | None:
    """Return the executable CLI binary name for a given harness/agent ID."""
    adapter = next((a for a in all_adapters() if a.id == agent_id), None)
    return getattr(adapter, "binary_name", None) if adapter else None


def resolve_adapter_for_request(
    client_type: str | None = None,
    user_agent: str = "",
    tools: list[dict] | None = None,
) -> BaseAdapter:
    """Resolve the specific harness adapter for an incoming request."""
    ua = (user_agent or "").lower()
    ct = (client_type or "").lower()

    if ct in ("omp", "oh-my-pi") or "omp" in ua:
        return OmpAdapter()
    if ct in ("claude_code", "claude-code", "claude") or "claude" in ua or "anthropic" in ua:
        return ClaudeCodeAdapter()
    if ct in ("opencode", "open-code") or "opencode" in ua:
        return OpenCodeAdapter()
    if ct in ("pi",) or "pi" in ua:
        return PiAdapter()

    # Inspect declared tool signatures
    if tools:
        tool_names = set()
        for t in tools:
            if isinstance(t, dict):
                name = t.get("name")
                if not name and "function" in t and isinstance(t["function"], dict):
                    name = t["function"].get("name")
                if name:
                    tool_names.add(name)
        if "Task" in tool_names:
            return ClaudeCodeAdapter()
        if "subagent" in tool_names:
            return OpenCodeAdapter()
        if "task" in tool_names:
            return OmpAdapter()

    return GenericAdapter()
