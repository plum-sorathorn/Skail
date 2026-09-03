from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from rudder.domain.security import PermissionSet, ProjectTrustLevel


@dataclass(frozen=True)
class AgentProfile:
    name: str
    description: str
    role: str
    tools: tuple[str, ...]
    permissions: PermissionSet
    prompt: str
    source: str
    revision: str
    model_policy: str | None = None
    delegation: bool = False
    response_schema: str | None = None
    role_floor: float = 0.0
    expected_calls: int = 1

    @property
    def write_capable(self) -> bool:
        return self.permissions.write or self.permissions.execute


class ProfileLoader:
    def __init__(
        self,
        *,
        project_root: Path,
        user_root: Path,
        builtins: dict[str, AgentProfile],
        known_tools: frozenset[str] | None = None,
    ) -> None:
        self.project_root = project_root
        self.user_root = user_root
        self.builtins = builtins
        self.known_tools = known_tools

    def load(
        self, name: str, *, trust: ProjectTrustLevel, ceiling: PermissionSet
    ) -> AgentProfile | None:
        sources: list[tuple[str, Path]] = []
        if trust is ProjectTrustLevel.TRUSTED:
            sources.append(
                ("project", self.project_root / ".rudder" / "agents" / name / "AGENTS.md")
            )
        sources.append(("user", self.user_root / "agents" / name / "AGENTS.md"))
        for label, path in sources:
            if path.is_file():
                return self._parse(name, label, path, ceiling)
        profile = self.builtins.get(name)
        if profile is not None and not ceiling.contains(profile.permissions):
            raise ValueError("profile exceeds permission ceiling")
        return profile

    def _parse(self, name: str, source: str, path: Path, ceiling: PermissionSet) -> AgentProfile:
        raw = path.read_text(encoding="utf-8")
        if not raw.startswith("---\n") or "\n---\n" not in raw[4:]:
            raise ValueError("profile requires YAML-like frontmatter")
        header, prompt = raw[4:].split("\n---\n", 1)
        values: dict[str, str] = {}
        for line in header.splitlines():
            if ":" not in line:
                raise ValueError("invalid profile frontmatter")
            key, value = line.split(":", 1)
            if key not in {
                "description", "role", "tools", "permissions", "model_policy",
                "delegation", "response_schema", "max_depth",
            }:
                raise ValueError(f"unknown profile field: {key}")
            values[key] = value.strip()
        if not values.get("description") or not values.get("role"):
            raise ValueError("profile description and role are required")
        tools = tuple(item.strip() for item in values.get("tools", "").split(",") if item.strip())
        if self.known_tools is not None and not set(tools) <= self.known_tools:
            raise ValueError("profile references unknown tools")
        requested_names = {
            item.strip() for item in values.get("permissions", "").split(",") if item.strip()
        }
        if not requested_names <= {"read", "write", "execute", "network"}:
            raise ValueError("unknown profile permission")
        requested = PermissionSet(**{item: True for item in requested_names})
        if not ceiling.contains(requested):
            raise ValueError("profile exceeds permission ceiling")
        delegation = values.get("delegation", "false").lower()
        if delegation not in {"true", "false"}:
            raise ValueError("delegation must be true or false")
        try:
            max_depth = int(values.get("max_depth", "0"))
        except ValueError as error:
            raise ValueError("max_depth must be an integer") from error
        if max_depth not in {0, 1}:
            raise ValueError("profile exceeds global delegation depth")
        return AgentProfile(
            name,
            values["description"],
            values["role"],
            tools,
            requested,
            prompt,
            source,
            hashlib.sha256(raw.encode()).hexdigest(),
            values.get("model_policy"),
            delegation == "true",
            values.get("response_schema"),
        )
