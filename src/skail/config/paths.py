from __future__ import annotations

from pathlib import Path


def user_data_dir() -> Path:
    return Path.home() / ".skail"


def user_config_path() -> Path:
    return user_data_dir() / "config.toml"


def project_config_path(workspace: Path) -> Path:
    return workspace / ".skail" / "config.toml"


def default_journal_path() -> Path:
    return user_data_dir() / "journal.sqlite"


def default_checkpoints_path() -> Path:
    return user_data_dir() / "checkpoints.sqlite"


def sessions_dir() -> Path:
    return user_data_dir() / "sessions"


def session_lock_path(session_id: str, base_dir: Path | None = None) -> Path:
    return (base_dir or sessions_dir()) / f"{session_id}.lock"


def session_export_path(session_id: str, base_dir: Path | None = None) -> Path:
    return (base_dir or sessions_dir()) / f"{session_id}-export.json"
