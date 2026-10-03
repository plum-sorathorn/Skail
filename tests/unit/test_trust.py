from __future__ import annotations

import json
import sqlite3
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


def test_trust_store_round_trips_unsigned_filesystem_identity(tmp_path: Path) -> None:
    path = tmp_path / "trust.sqlite"
    identity = WorkspaceIdentity(
        canonical_path="/work/large-identity",
        device=2**63 + 7,
        inode=2**64 - 1,
    )
    store = ProjectTrustStore(path)

    store.set_level(identity, ProjectTrustLevel.TRUSTED)

    assert ProjectTrustStore(path).assess(identity).level is ProjectTrustLevel.TRUSTED
    changed = identity.model_copy(update={"inode": identity.inode - 1})
    assert store.assess(changed).level is ProjectTrustLevel.UNTRUSTED
    with sqlite3.connect(path) as connection:
        stored = connection.execute(
            "SELECT typeof(device),device,typeof(inode),inode FROM trust_records"
        ).fetchone()
    assert stored == ("text", str(identity.device), "text", str(identity.inode))


def test_trust_store_migrates_existing_integer_identity_rows(tmp_path: Path) -> None:
    path = tmp_path / "trust.sqlite"
    identity = WorkspaceIdentity(
        canonical_path="/work/existing",
        device=2049,
        inode=42,
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE trust_records (workspace_key TEXT PRIMARY KEY, "
            "canonical_path TEXT NOT NULL, device INTEGER NOT NULL, inode INTEGER NOT NULL, "
            "level TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO trust_records VALUES (?,?,?,?,?,?,?)",
            (identity.key, identity.canonical_path, 2049, 42, "trusted", 7, "2026-10-03"),
        )

    store = ProjectTrustStore(path)

    assert store.assess(identity).level is ProjectTrustLevel.TRUSTED
    with sqlite3.connect(path) as connection:
        columns = connection.execute("PRAGMA table_info(trust_records)").fetchall()
        row = connection.execute(
            "SELECT typeof(device),device,typeof(inode),inode,revision FROM trust_records"
        ).fetchone()
    assert {column[1]: column[2] for column in columns}["inode"] == "TEXT"
    assert row == ("text", "2049", "text", "42", 7)
    store.set_level(identity, ProjectTrustLevel.DENIED)
    with sqlite3.connect(path) as connection:
        updated = connection.execute(
            "SELECT level,revision FROM trust_records WHERE workspace_key=?",
            (identity.key,),
        ).fetchone()
    assert updated == ("denied", 8)


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
