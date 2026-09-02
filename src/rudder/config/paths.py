from __future__ import annotations

from pathlib import Path


def user_data_dir() -> Path:
    return Path.home() / ".rudder"


def user_config_path() -> Path:
    return user_data_dir() / "config.toml"


def project_config_path(workspace: Path) -> Path:
    return workspace / ".rudder" / "config.toml"
