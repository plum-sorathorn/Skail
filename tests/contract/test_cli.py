from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from shutil import which

ROOT = Path(__file__).resolve().parents[2]


def run_module(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "skail.cli.main", *arguments],
        cwd=ROOT,
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


def test_fake_provider_smoke_is_offline_and_deterministic() -> None:
    result = run_module("smoke", "--fake-provider")
    assert result.returncode == 0
    assert result.stdout.strip() == "Skail fake-provider smoke: ok"
    assert result.stderr == ""


def test_developer_smoke_script_uses_the_same_contract() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/smoke.py", "--fake-provider"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "Skail fake-provider smoke: ok"
    assert result.stderr == ""


def test_installed_console_script_exposes_help_and_version() -> None:
    executable = which("skail")
    assert executable is not None, "install the project before running contract tests"

    help_result = subprocess.run(
        [executable, "--help"], cwd=ROOT, capture_output=True, text=True
    )
    version_result = subprocess.run(
        [executable, "--version"], cwd=ROOT, capture_output=True, text=True
    )

    assert help_result.returncode == 0
    assert "Skail" in help_result.stdout
    assert version_result.returncode == 0
    assert version_result.stdout.strip() == "skail 0.1.0"
