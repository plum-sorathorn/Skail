from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from skail.agents.profile_loader import ProfileLoader
from skail.domain.security import PermissionSet, ProjectTrustLevel
from skail.tools.extensions import ExtensionLoader, ExtensionSpec
from skail.tools.registry import SideEffect, ToolMetadata, ToolRegistry
from skail.tools.skills import load_bounded_contexts


def test_project_profile_is_inactive_until_trusted_and_revision_is_pinned(tmp_path: Path) -> None:
    project = tmp_path / ".skail" / "agents" / "worker"
    project.mkdir(parents=True)
    source = project / "AGENTS.md"
    source.write_text(
        "---\n"
        "description: Worker\nrole: implementer\n"
        "tools: read_file,write_file\npermissions: read,write\n"
        "---\nFirst revision",
        encoding="utf-8",
    )
    loader = ProfileLoader(project_root=tmp_path, user_root=tmp_path / "user", builtins={})
    assert (
        loader.load("worker", trust=ProjectTrustLevel.UNTRUSTED, ceiling=PermissionSet(read=True))
        is None
    )
    profile = loader.load(
        "worker", trust=ProjectTrustLevel.TRUSTED, ceiling=PermissionSet(read=True, write=True)
    )
    assert profile is not None and profile.source == "project"
    source.write_text(
        source.read_text(encoding="utf-8").replace("First", "Second"), encoding="utf-8"
    )
    assert profile.prompt == "First revision"


def test_child_profile_cannot_expand_permission_ceiling(tmp_path: Path) -> None:
    project = tmp_path / ".skail" / "agents" / "worker"
    project.mkdir(parents=True)
    (project / "AGENTS.md").write_text(
        "---\ndescription: Bad\nrole: worker\ntools: execute\npermissions: execute\n---\nNo",
        encoding="utf-8",
    )
    loader = ProfileLoader(project_root=tmp_path, user_root=tmp_path / "user", builtins={})
    with pytest.raises(ValueError, match="permission ceiling"):
        loader.load("worker", trust=ProjectTrustLevel.TRUSTED, ceiling=PermissionSet(read=True))


def test_extensions_are_opt_in_fail_soft_and_unknown_is_approval_worthy() -> None:
    registry = ToolRegistry(
        [
            ToolMetadata(
                name="read_file",
                description="read",
                source="core",
                version="1",
                schema={"type": "object"},
                side_effect=SideEffect.READ_ONLY,
                approval="allow",
                profiles=frozenset({"lead"}),
            )
        ]
    )
    loader = ExtensionLoader(registry)
    unknown = ExtensionSpec(
        "extra",
        "custom",
        enabled=True,
        required=False,
        tools=({"name": "extra_tool", "description": "x", "schema": {"type": "object"}},),
    )
    loader.activate(unknown, trusted=True)
    assert registry.get("extra_tool").side_effect is SideEffect.UNKNOWN
    assert registry.get("extra_tool").approval == "ask"
    assert (
        loader.activate(
            ExtensionSpec("broken", "mcp", enabled=True, required=False, load_error="offline"),
            trusted=True,
        ).active
        is False
    )
    with pytest.raises(ValueError, match="collision"):
        loader.activate(
            ExtensionSpec(
                "collision",
                "custom",
                enabled=True,
                required=True,
                tools=({"name": "read_file", "schema": {"type": "object"}},),
            ),
            trusted=True,
        )


def test_extension_factory_receives_secret_out_of_band_and_registration_is_atomic() -> None:
    registry = ToolRegistry()
    observed: list[str] = []

    def factory(secrets: Mapping[str, str]) -> tuple[object, ...]:
        observed.append(secrets["TOKEN"])
        return (object(),)

    status = ExtensionLoader(registry).activate(
        ExtensionSpec(
            "custom",
            "custom",
            enabled=True,
            tools=(
                {"name": "one", "schema": {"type": "object"}},
                {"name": "two", "schema": {"type": "object"}},
            ),
            factory=factory,
        ),
        trusted=True,
        secrets={"TOKEN": "canary"},
    )
    assert observed == ["canary"]
    assert len(status.loaded_tools) == 1
    assert registry.names == frozenset({"one", "two"})


def test_skill_context_is_rooted_redacted_bounded_and_source_labelled(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    root.mkdir()
    source = root / "SKILL.md"
    source.write_text("canary-" + "x" * 100, encoding="utf-8")
    from skail.runtime.redaction import RedactionRegistry

    redactor = RedactionRegistry()
    redactor.register("canary")
    loaded = load_bounded_contexts(
        (source,), root=root, label="user-skill", trust=ProjectTrustLevel.TRUSTED,
        project_owned=False, redactor=redactor, total_limit=20,
    )
    assert loaded[0].label == "user-skill:SKILL.md"
    assert "canary" not in loaded[0].content
    assert len(loaded[0].content) <= 20


def test_optional_extension_failure_redacts_secret_and_does_not_partially_register() -> None:
    from skail.runtime.redaction import RedactionRegistry

    redactor = RedactionRegistry()
    redactor.register("canary")

    def broken(_secrets: Mapping[str, str]) -> tuple[object, ...]:
        raise RuntimeError("failed with canary")

    registry = ToolRegistry()
    status = ExtensionLoader(registry, redactor).activate(
        ExtensionSpec(
            "broken", "custom", enabled=True,
            tools=({"name": "not-added", "schema": {"type": "object"}},),
            factory=broken,
        ),
        trusted=True,
    )
    assert status.diagnostic == "failed with [REDACTED]"
    assert registry.names == frozenset()
