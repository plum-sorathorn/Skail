from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from skail.runtime.redaction import RedactionRegistry
from skail.tools.registry import SideEffect, ToolMetadata, ToolRegistry


@dataclass(frozen=True)
class ExtensionSpec:
    name: str
    kind: str
    enabled: bool = False
    required: bool = False
    tools: tuple[dict[str, Any], ...] = ()
    load_error: str | None = None
    factory: Callable[[Mapping[str, str]], tuple[Any, ...]] | None = None


@dataclass(frozen=True)
class ExtensionStatus:
    name: str
    active: bool
    diagnostic: str | None = None
    loaded_tools: tuple[Any, ...] = ()


class ExtensionLoader:
    def __init__(
        self,
        registry: ToolRegistry,
        redactor: RedactionRegistry | None = None,
    ) -> None:
        self.registry = registry
        self.redactor = redactor or RedactionRegistry()

    def activate(
        self,
        spec: ExtensionSpec,
        *,
        trusted: bool,
        collision_overrides: frozenset[str] = frozenset(),
        secrets: Mapping[str, str] | None = None,
    ) -> ExtensionStatus:
        if not spec.enabled:
            return ExtensionStatus(spec.name, False, "disabled")
        if not trusted:
            return ExtensionStatus(spec.name, False, "project is untrusted")
        if spec.load_error:
            if spec.required:
                raise RuntimeError(spec.load_error)
            return ExtensionStatus(spec.name, False, spec.load_error)
        names = tuple(str(raw["name"]) for raw in spec.tools)
        if len(names) != len(set(names)):
            raise ValueError("tool name collision within extension")
        collisions = self.registry.names.intersection(names)
        unresolved = collisions.difference(collision_overrides)
        if unresolved:
            raise ValueError(f"tool name collision: {sorted(unresolved)[0]}")
        if collisions:
            raise ValueError("explicit overrides must be resolved before registry assembly")
        metadata: list[ToolMetadata] = []
        for raw in spec.tools:
            name = str(raw["name"])
            effect = SideEffect(raw.get("side_effect", SideEffect.UNKNOWN))
            metadata.append(
                ToolMetadata(
                    name=name,
                    description=str(raw.get("description", name)),
                    source=f"extension:{spec.name}",
                    version=str(raw.get("version", "1")),
                    schema=dict(raw["schema"]),
                    side_effect=effect,
                    approval="allow" if effect is SideEffect.READ_ONLY else "ask",
                    profiles=frozenset(raw.get("profiles", ("lead",))),
                    network_required=bool(raw.get("network", False)),
                    credential_required=bool(raw.get("credentials", False)),
                )
            )
        try:
            loaded = () if spec.factory is None else spec.factory(secrets or {})
        except Exception as error:
            if spec.required:
                raise
            return ExtensionStatus(
                spec.name, False, self.redactor.scrub_text(str(error))
            )
        for item in metadata:
            self.registry.register(item)
        return ExtensionStatus(spec.name, True, loaded_tools=loaded)
