from __future__ import annotations

import hashlib
import os
from pathlib import Path

from skail.domain.security import WorkspaceIdentity, identify_workspace


def user_data_dir(root: Path | None = None) -> Path:
    return (root or (Path.home() / ".skail")).resolve(strict=False)


def user_config_path() -> Path:
    return user_data_dir() / "config.toml"


def workspace_state_dir(identity: WorkspaceIdentity, *, root: Path | None = None) -> Path:
    state_root = user_data_dir(root)
    namespace = _workspace_namespace(identity)
    return _under_root(state_root / "workspaces" / namespace, state_root)


def workspace_state_path(
    identity: WorkspaceIdentity,
    relative_path: str | Path,
    *,
    root: Path | None = None,
) -> Path:
    state_path = workspace_state_dir(identity, root=root) / relative_path
    return _under_root(state_path, user_data_dir(root))


def project_config_path(
    workspace: Path | WorkspaceIdentity,
    *,
    root: Path | None = None,
) -> Path:
    identity = (
        workspace
        if isinstance(workspace, WorkspaceIdentity)
        else identify_workspace(workspace)
    )
    return workspace_state_path(identity, "config.toml", root=root)


def default_journal_path() -> Path:
    return user_data_dir() / "journal.sqlite"


def default_checkpoints_path() -> Path:
    return user_data_dir() / "checkpoints.sqlite"


def sessions_dir() -> Path:
    return user_data_dir() / "sessions"


def catalog_cache_path(provider: str = "llmgateway") -> Path:
    return user_data_dir() / "catalog" / f"{provider}.json"


def session_lock_path(session_id: str, base_dir: Path | None = None) -> Path:
    return (base_dir or sessions_dir()) / f"{session_id}.lock"


def session_export_path(session_id: str, base_dir: Path | None = None) -> Path:
    return (base_dir or sessions_dir()) / f"{session_id}-export.json"


def _workspace_namespace(identity: WorkspaceIdentity) -> str:
    value = "\0".join(
        (os.path.normcase(identity.canonical_path), str(identity.device), str(identity.inode))
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _under_root(path: Path, root: Path) -> Path:
    resolved_root = root.resolve(strict=False)
    resolved_path = path.resolve(strict=False)
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError("state path escapes global state root") from error
    return resolved_path
