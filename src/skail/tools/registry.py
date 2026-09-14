from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SideEffect(StrEnum):
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    EXTERNAL_WRITE = "external_write"
    UNKNOWN = "unknown"


class ToolMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    source: str = Field(min_length=1)
    version: str = Field(min_length=1)
    tool_schema: dict[str, Any] = Field(alias="schema")
    side_effect: SideEffect
    approval: str
    profiles: frozenset[str]
    path_required: bool = False
    network_required: bool = False
    credential_required: bool = False

    @model_validator(mode="after")
    def validate_schema(self) -> ToolMetadata:
        if self.tool_schema.get("type") != "object":
            raise ValueError("tool schema must be a JSON object schema")
        return self


class ToolRegistry:
    def __init__(self, tools: list[ToolMetadata] | tuple[ToolMetadata, ...] = ()) -> None:
        self._tools: dict[str, ToolMetadata] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: ToolMetadata) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolMetadata:
        return self._tools[name]

    def visible_to(self, profile: str) -> tuple[ToolMetadata, ...]:
        return tuple(tool for tool in self._tools.values() if profile in tool.profiles)

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._tools)
