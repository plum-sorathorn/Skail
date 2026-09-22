from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from skail.cli.exit_codes import EXIT_BLOCKED, EXIT_FAILURE, EXIT_OK, EXIT_USAGE

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


def run_cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "skail.cli.main", *args],
        cwd=CLI_WORKSPACE,
        capture_output=True,
        text=True,
        env=env,
    )


def run_cli_isolated(
    home: Path, *args: str
) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "USERPROFILE": str(home),
        "APPDATA": str(home / "AppData"),
        "LOCALAPPDATA": str(home / "AppData" / "Local"),
    }
    return subprocess.run(
        [sys.executable, "-m", "skail.cli.main", *args],
        cwd=home,
        capture_output=True,
        text=True,
        env=env,
    )


def test_cli_usage_error_on_conflicting_output_modes() -> None:
    result = run_cli("--print", "--json", "hello")
    assert result.returncode == EXIT_USAGE
    assert (
        "cannot specify both" in result.stderr.lower()
        or "conflict" in result.stderr.lower()
    )


def test_cli_usage_error_on_conflicting_trust_flags() -> None:
    result = run_cli("--approve-project", "--deny-project")
    assert result.returncode == EXIT_USAGE
    assert (
        "cannot specify both" in result.stderr.lower()
        or "conflict" in result.stderr.lower()
    )


def test_cli_rejects_old_skail_aliases() -> None:
    for alias in ("proxy", "serve", "oma", "daemon", "plugin", "slm"):
        result = run_cli(alias)
        assert result.returncode == EXIT_USAGE
        assert (
            "not supported" in result.stderr.lower()
            or "removed" in result.stderr.lower()
            or "unrecognized" in result.stderr.lower()
            or "invalid" in result.stderr.lower()
        )

    # Old options
    for opt in ("--proxy", "--port", "--host"):
        result = run_cli(opt)
        assert result.returncode == EXIT_USAGE


def test_cli_subcommand_config(tmp_path: Path) -> None:
    result_show = run_cli("config", "show")
    assert result_show.returncode == EXIT_OK
    assert "routing" in result_show.stdout

    result_path = run_cli("config", "path")
    assert result_path.returncode == EXIT_OK
    assert ".skail" in result_path.stdout


def test_cli_subprocess_does_not_write_runtime_state_to_checkout() -> None:
    result = run_cli("config", "path")

    assert result.returncode == EXIT_OK
    assert not (CLI_WORKSPACE / ".skail").exists()
    assert (CLI_HOME / ".skail").exists()


def test_cli_subcommand_sessions(tmp_path: Path) -> None:
    result = run_cli("sessions", "list")
    assert result.returncode == EXIT_OK


def test_cli_subcommand_auth() -> None:
    result = run_cli("auth", "status")
    assert result.returncode == EXIT_OK
    assert "credentials" in result.stdout.lower() or "provider" in result.stdout.lower()


def test_cli_subcommand_models() -> None:
    result = run_cli("models", "list")
    assert result.returncode == EXIT_OK
    assert "model" in result.stdout.lower()


def test_cli_approve_and_deny_project(tmp_path: Path) -> None:
    approve_result = run_cli("--approve-project")
    assert approve_result.returncode == EXIT_OK

    deny_result = run_cli("--deny-project")
    assert deny_result.returncode == EXIT_OK


def test_cli_isolated_subprocess_uses_temporary_home(tmp_path: Path) -> None:
    result = run_cli_isolated(tmp_path, "config", "path")
    assert result.returncode == EXIT_OK
    assert str(tmp_path / ".skail") in result.stdout


def test_cli_normal_mode_fails_when_no_credentials() -> None:
    import os

    clean_env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "USERPROFILE": os.environ.get("USERPROFILE", ""),
        "APPDATA": os.environ.get("APPDATA", ""),
        "LOCALAPPDATA": os.environ.get("LOCALAPPDATA", ""),
    }
    result = run_cli(
        "-p", "say hello without credentials",
        env=clean_env,
    )
    assert result.returncode == EXIT_FAILURE
    assert (
        "credentials" in result.stderr.lower()
        or "provider" in result.stderr.lower()
    )


def test_cli_returns_blocked_exit_code_on_interrupted_run(tmp_path: Path) -> None:
    import argparse
    import asyncio
    from datetime import UTC, datetime, timedelta

    from fakes.provider import FakeProviderAdapter

    import skail.cli.main as cli_main
    from skail.cli.main import RuntimeModelSet, _execute_instruction
    from skail.config.models import SkailConfig
    from skail.providers.catalog import ModelCatalog
    from skail.runtime.interrupts import QuestionStore
    from skail.runtime.redaction import RedactionRegistry
    from skail.sessions.checkpoints import CheckpointStore
    from skail.sessions.journal import Journal
    from skail.sessions.service import SessionService
    from skail.tools.approvals import ApprovalStore
    from tests.fakes.models import ScriptedChatModel, tool_call_message

    journal = Journal(tmp_path / "journal.sqlite")
    journal.migrate()
    checkpoints = CheckpointStore(tmp_path / "checkpoints.sqlite")
    checkpoints.initialize()
    redaction = RedactionRegistry()
    approvals = ApprovalStore(tmp_path / "approvals.sqlite")
    question_store = QuestionStore(tmp_path / "questions.sqlite")

    session_service = SessionService(
        journal=journal,
        checkpoints=checkpoints,
        sessions_dir=tmp_path / "sessions",
    )
    session = session_service.create_session(title="Blocked Test")
    args = argparse.Namespace(
        prompt=["call ask user"],
        print_mode=True,
        json_mode=False,
        lead_model="lead-model",
        default_model="lead-model",
        budget="10.00",
        max_agents=1,
        delegation="auto",
    )
    tool_msg = tool_call_message(
        "ask_user",
        {"prompt": "Need approval?", "reason": "confirmation"},
        call_id="call-1",
    )
    model = ScriptedChatModel(responses=[tool_msg])

    orig_builder = cli_main._build_runtime_models
    try:
        cli_main._build_runtime_models = lambda a, r, p="": RuntimeModelSet(  # type: ignore[assignment]
            {"lead-model": model, "implementer-model": model},
            "lead-model",
            "lead-model",
            {"injected": FakeProviderAdapter(model)},
            catalog=ModelCatalog.from_entries(
                (), now=datetime.now(UTC), price_max_age=timedelta(days=30)
            ),
            config=SkailConfig(),
            redaction=r,
        )
        code = asyncio.run(
            _execute_instruction(
                prompt="call ask user",
                session=session,
                journal=journal,
                checkpoints=checkpoints,
                redaction=redaction,
                approvals=approvals,
                question_store=question_store,
                workspace=tmp_path,
                args=args,
            )
        )
        assert code == EXIT_BLOCKED
    finally:
        cli_main._build_runtime_models = orig_builder
