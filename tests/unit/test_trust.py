from __future__ import annotations

import json
from pathlib import Path

import pytest

from skail.config import ProjectTrustStore
from skail.domain.security import (
    ProjectExtensionKind,
    ProjectTrustLevel,
    WorkspaceIdentity,
    identify_workspace,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "config"
pytestmark = pytest.mark.unit


def test_workspace_identity_uses_canonical_path_and_filesystem_identity(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    identity = identify_workspace(workspace / ".")

    assert identity.canonical_path == str(workspace.resolve())
    assert isinstance(identity.device, int)
    assert isinstance(identity.inode, int)


def test_lexical_workspace_paths_resolve_to_the_same_identity(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    root_identity = identify_workspace(workspace)
    equivalent_identity = identify_workspace(workspace / ".")

    assert root_identity == equivalent_identity
    assert root_identity.key == equivalent_identity.key


def test_platform_workspace_identity_fixtures_round_trip_deterministically() -> None:
    fixtures = json.loads((FIXTURES / "workspace_identities.json").read_text(encoding="utf-8"))

    linux = WorkspaceIdentity.model_validate(fixtures["linux"])
    windows = WorkspaceIdentity.model_validate(fixtures["windows"])

    assert linux.model_dump(mode="json") == fixtures["linux"]
    assert windows.model_dump(mode="json") == fixtures["windows"]


def test_unknown_workspace_starts_untrusted_and_requires_a_decision(tmp_path: Path) -> None:
    store = ProjectTrustStore(tmp_path / "trust.json")
    identity = WorkspaceIdentity(
        canonical_path="/work/skail",
        device=2049,
        inode=42,
    )

    assessment = store.assess(identity)

    assert assessment.level is ProjectTrustLevel.UNTRUSTED
    assert assessment.requires_prompt is True
    assert "no trust decision" in assessment.reason


def test_trusted_and_denied_decisions_are_explicit_and_persisted(tmp_path: Path) -> None:
    trust_path = tmp_path / "trust.json"
    trusted_identity = WorkspaceIdentity(
        canonical_path="/work/trusted",
        device=2049,
        inode=10,
    )
    denied_identity = WorkspaceIdentity(
        canonical_path="/work/denied",
        device=2049,
        inode=11,
    )
    store = ProjectTrustStore(trust_path)

    store.set_level(trusted_identity, ProjectTrustLevel.TRUSTED)
    store.set_level(denied_identity, ProjectTrustLevel.DENIED)
    reloaded = ProjectTrustStore(trust_path)

    assert reloaded.assess(trusted_identity).level is ProjectTrustLevel.TRUSTED
    assert reloaded.assess(trusted_identity).requires_prompt is False
    assert reloaded.assess(denied_identity).level is ProjectTrustLevel.DENIED
    assert reloaded.assess(denied_identity).requires_prompt is False


def test_replacing_a_workspace_at_the_same_path_requires_a_new_decision(tmp_path: Path) -> None:
    store = ProjectTrustStore(tmp_path / "trust.json")
    original = WorkspaceIdentity(
        canonical_path="/work/skail",
        device=2049,
        inode=42,
    )
    replacement = WorkspaceIdentity(
        canonical_path="/work/skail",
        device=2049,
        inode=99,
    )
    store.set_level(original, ProjectTrustLevel.TRUSTED)

    assessment = store.assess(replacement)

    assert assessment.level is ProjectTrustLevel.UNTRUSTED
    assert assessment.requires_prompt is True
    assert "identity changed" in assessment.reason


def test_all_project_extensions_are_gated_by_trust(tmp_path: Path) -> None:
    store = ProjectTrustStore(tmp_path / "trust.json")
    identity = WorkspaceIdentity(
        canonical_path="/work/skail",
        device=2049,
        inode=42,
    )
    extension_kinds = (
        ProjectExtensionKind.CONFIG,
        ProjectExtensionKind.PROFILE,
        ProjectExtensionKind.SKILL,
        ProjectExtensionKind.TOOL,
        ProjectExtensionKind.MCP,
        ProjectExtensionKind.APPROVAL_RULE,
        ProjectExtensionKind.PROVIDER_REFERENCE,
    )

    untrusted = store.assess(identity)
    assert all(not untrusted.permits(kind) for kind in extension_kinds)

    store.set_level(identity, ProjectTrustLevel.DENIED)
    denied = store.assess(identity)
    assert all(not denied.permits(kind) for kind in extension_kinds)

    store.set_level(identity, ProjectTrustLevel.TRUSTED)
    trusted = store.assess(identity)
    assert all(trusted.permits(kind) for kind in extension_kinds)


def test_revocation_signals_active_project_tasks_before_their_next_tool_call(
    tmp_path: Path,
) -> None:
    store = ProjectTrustStore(tmp_path / "trust.json")
    identity = WorkspaceIdentity(
        canonical_path="/work/skail",
        device=2049,
        inode=42,
    )
    store.set_level(identity, ProjectTrustLevel.TRUSTED)
    signal = store.revocation_signal(identity)

    assert signal.is_set() is False

    store.set_level(identity, ProjectTrustLevel.UNTRUSTED)

    assert signal.is_set() is True


def test_revocation_signal_observes_another_store_instance(tmp_path: Path) -> None:
    trust_path = tmp_path / "trust.sqlite"
    identity = WorkspaceIdentity(
        canonical_path="/work/shared",
        device=2049,
        inode=77,
    )
    first = ProjectTrustStore(trust_path)
    first.set_level(identity, ProjectTrustLevel.TRUSTED)
    signal = first.revocation_signal(identity)

    ProjectTrustStore(trust_path).set_level(identity, ProjectTrustLevel.DENIED)

    assert signal.is_set() is True
