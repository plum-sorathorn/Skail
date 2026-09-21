from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from skail.config.paths import project_config_path, workspace_state_path
from skail.domain.security import WorkspaceIdentity


class StateMigrationError(ValueError):
    """Raised when recognized legacy state cannot be imported safely."""


@dataclass(frozen=True)
class MigrationRecord:
    source: str
    destination: str
    outcome: str
    source_digest: str


_LEGACY_FILES = (
    ("config.toml", "config"),
    ("approvals.sqlite", "approvals"),
    ("questions.sqlite", "questions"),
)


def migrate_legacy_workspace_state(
    identity: WorkspaceIdentity,
    workspace: Path,
    *,
    root: Path | None = None,
) -> tuple[MigrationRecord, ...]:
    workspace_root = workspace.resolve(strict=True)
    legacy_root = workspace_root / ".skail"
    if not legacy_root.exists():
        return ()
    if legacy_root.is_symlink() or not legacy_root.is_dir():
        raise StateMigrationError("legacy .skail state must be a real directory")

    records: list[MigrationRecord] = []
    for filename, kind in _LEGACY_FILES:
        source = legacy_root / filename
        if not source.exists():
            continue
        _assert_legacy_file(source, workspace_root)
        if kind == "config":
            destination = project_config_path(identity, root=root)
        else:
            destination = workspace_state_path(identity, filename, root=root)
        outcome, digest = _import_file(source, destination)
        records.append(
            MigrationRecord(
                source=str(source.relative_to(workspace_root)),
                destination=str(destination),
                outcome=outcome,
                source_digest=digest,
            )
        )

    if records:
        _write_receipt(identity, records, root=root)
    return tuple(records)


def _assert_legacy_file(source: Path, workspace: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise StateMigrationError(f"legacy state is not a regular file: {source.name}")
    try:
        source.resolve(strict=True).relative_to(workspace)
    except ValueError as error:
        raise StateMigrationError(f"legacy state escapes workspace: {source.name}") from error


def _import_file(source: Path, destination: Path) -> tuple[str, str]:
    source_digest = _digest(source)
    if destination.exists():
        if not destination.is_file() or _digest(destination) != source_digest:
            raise StateMigrationError(
                f"legacy state conflicts with global state: {source.name}"
            )
        return "already_imported", source_digest
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return "imported", source_digest


def _write_receipt(
    identity: WorkspaceIdentity,
    records: list[MigrationRecord],
    *,
    root: Path | None,
) -> None:
    receipt = workspace_state_path(identity, "migration.json", root=root)
    payload = {
        "schema_version": 1,
        "workspace_identity": {
            "device": identity.device,
            "inode": identity.inode,
            "canonical_path": identity.canonical_path,
        },
        "records": [asdict(record) for record in records],
    }
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
