from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from shutil import which

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLI_WORKSPACE = ROOT
CLI_HOME = ROOT


@pytest.fixture(autouse=True)
def isolate_cli_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys.modules[__name__], "CLI_WORKSPACE", tmp_path)
    home = tmp_path / "home"
    monkeypatch.setattr(sys.modules[__name__], "CLI_HOME", home)
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("APPDATA", str(home / "AppData"))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData" / "Local"))
    monkeypatch.setenv("HOME", str(home))


def run_module(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "skail.cli.main", *arguments],
        cwd=CLI_WORKSPACE,
        capture_output=True,
        text=True,
    )


def test_help_identifies_the_native_skail_command() -> None:
    result = run_module("--help")
    assert result.returncode == 0
    assert "Skail" in result.stdout
    assert ("R" + "udder") not in result.stdout


def test_version_is_the_new_distribution_version() -> None:
    result = run_module("--version")
    assert result.returncode == 0
    assert result.stdout.strip() == "skail 0.1.0"


def test_fake_provider_flag_is_not_exposed() -> None:
    result = run_module("--help")
    assert "--fake-provider" not in result.stdout


def test_developer_smoke_script_uses_the_same_contract() -> None:
    legacy_state = ROOT / ".skail"
    before = (
        tuple(sorted(path.name for path in legacy_state.iterdir()))
        if legacy_state.is_dir()
        else ()
    )
    result = subprocess.run(
        [sys.executable, ROOT / "scripts" / "smoke.py"],
        cwd=CLI_WORKSPACE,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "Skail offline smoke: ok"
    assert result.stderr == ""
    after = (
        tuple(sorted(path.name for path in legacy_state.iterdir()))
        if legacy_state.is_dir()
        else ()
    )
    assert after == before


def test_installed_console_script_exposes_help_and_version() -> None:
    executable = which("skail")
    assert executable is not None, "install the project before running contract tests"

    help_result = subprocess.run(
        [executable, "--help"], cwd=CLI_WORKSPACE, capture_output=True, text=True
    )
    version_result = subprocess.run(
        [executable, "--version"], cwd=CLI_WORKSPACE, capture_output=True, text=True
    )

    assert help_result.returncode == 0
    assert "Skail" in help_result.stdout
    assert version_result.returncode == 0
    assert version_result.stdout.strip() == "skail 0.1.0"
