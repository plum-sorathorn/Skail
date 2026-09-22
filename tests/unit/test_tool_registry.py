from __future__ import annotations

import pytest

from skail.runtime.redaction import RedactionRegistry
from skail.tools.artifacts import ArtifactStore
from skail.tools.assembly import default_registry
from skail.tools.registry import SideEffect, ToolMetadata, ToolRegistry


def _tool(name: str = "read_file") -> ToolMetadata:
    return ToolMetadata(
        name=name,
        description="Read one file",
        source="deepagents",
        version="0.7.13",
        schema={"type": "object", "properties": {"path": {"type": "string"}}},
        side_effect=SideEffect.READ_ONLY,
        approval="allow",
        profiles=frozenset({"lead", "explorer"}),
    )


def test_registry_rejects_duplicate_names_and_unknown_schemas() -> None:
    registry = ToolRegistry([_tool()])
    with pytest.raises(ValueError, match="duplicate tool name"):
        registry.register(_tool())
    with pytest.raises(ValueError, match="schema"):
        ToolMetadata(
            name="broken",
            description="broken",
            source="custom",
            version="1",
            schema={"type": "mystery"},
            side_effect=SideEffect.UNKNOWN,
            approval="ask",
            profiles=frozenset({"lead"}),
        )


def test_large_output_is_redacted_before_artifact_storage(tmp_path) -> None:
    redaction = RedactionRegistry()
    redaction.register("canary-secret")
    result = ArtifactStore(tmp_path, redaction, excerpt_chars=20).capture(
        "read_file", "prefix canary-secret " + "x" * 100
    )
    assert result.truncated is True
    assert result.artifact_path is not None
    assert "canary-secret" not in result.excerpt
    assert "canary-secret" not in result.artifact_path.read_text(encoding="utf-8")


def test_default_surface_has_stable_complete_metadata() -> None:
    registry = default_registry()
    assert registry.names == frozenset(
        {
            "ls", "glob", "grep", "read_file", "write_file", "edit_file", "execute",
            "write_todos", "task", "skills", "memory", "ask_user",
        }
    )
    for name in registry.names:
        tool = registry.get(name)
        assert tool.source and tool.version and tool.description
        assert tool.profiles and tool.approval and tool.tool_schema
