"""Installation detection and package-manager commands for the CLI."""
from __future__ import annotations

import importlib.metadata
import os
import sys
from pathlib import Path


def _module_path() -> Path:
    import skail
    return Path(skail.__file__).resolve()


def _is_editable() -> bool:
    try:
        return not _module_path().is_relative_to(Path(sys.prefix).resolve())
    except (ImportError, OSError, ValueError):
        return False


def _is_uv_tool() -> bool:
    return os.sep.join(("uv", "tools")) in str(Path(sys.executable))


def detect_install_method() -> str:
    if os.environ.get("SKAIL_WHEEL_DIR"):
        return "npm"
    try:
        uv = _is_uv_tool()
        editable = _is_editable()
    except (ImportError, OSError, ValueError):
        editable = False
        uv = False
    if uv:
        return "uv-tool-editable" if editable else "uv-tool"
    try:
        importlib.metadata.distribution("skail")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"
    return "pip-editable" if editable else "pip"


def upgrade_command(method: str) -> str | None:
    py = sys.executable or "python"
    return {
        "uv-tool": "uv tool upgrade --reinstall skail",
        "uv-tool-editable": "uv tool install --reinstall --editable .",
        "pip-editable": f'"{py}" -m pip install --force-reinstall -e .',
        "npm": "npm install -g skail@latest",
        "pip": f'"{py}" -m pip install --force-reinstall --upgrade skail',
    }.get(method)


def uninstall_hint(method: str) -> str | None:
    if method.startswith("uv-tool"):
        return "uv tool uninstall skail"
    if method.startswith("pip"):
        return "pip uninstall skail"
    if method == "npm":
        return "npm uninstall -g skail"
    return None
