from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src" / "rudder"
FORBIDDEN_MODULES = ("autoconduck", "legacy")


def test_runtime_has_no_legacy_import_or_path_escape() -> None:
    violations: list[str] = []
    for path in SOURCE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                forbidden = any(
                    alias.name == name or alias.name.startswith(f"{name}.")
                    for alias in node.names
                    for name in FORBIDDEN_MODULES
                )
                if forbidden:
                    violations.append(f"{path}: forbidden import")
            elif isinstance(node, ast.ImportFrom) and node.module:
                forbidden = any(
                    node.module == name or node.module.startswith(f"{name}.")
                    for name in FORBIDDEN_MODULES
                )
                if forbidden:
                    violations.append(f"{path}: forbidden from-import")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                normalized = node.value.replace("\\", "/").lower()
                if "legacy/autoconduck" in normalized:
                    violations.append(f"{path}: forbidden archive path literal")
    assert violations == []


def test_core_import_requires_no_credentials_or_legacy_modules() -> None:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.endswith("_API_KEY") and not key.endswith("_TOKEN")
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, rudder; "
            "assert not any(name == 'autoconduck' or name.startswith('autoconduck.') "
            "or name == 'legacy' or name.startswith('legacy.') for name in sys.modules)",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_runtime_does_not_import_textual() -> None:
    violations: list[str] = []
    for path in SOURCE.rglob("*.py"):
        rel = path.relative_to(SOURCE).as_posix()
        # Only files within tui/ can import textual (and projection.py must not)
        if rel.startswith("tui/") and rel != "tui/projection.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(
                    alias.name == "textual" or alias.name.startswith("textual.")
                    for alias in node.names
                ):
                    violations.append(f"{path}: imports textual")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "textual" or node.module.startswith("textual."):
                    violations.append(f"{path}: imports textual")
    assert violations == []

