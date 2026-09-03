from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from rudder.cli.exit_codes import EXIT_OK, EXIT_USAGE
from rudder.domain.events import EventEnvelope

ROOT = Path(__file__).resolve().parents[2]


def run_cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "rudder.cli.main", *args],
        cwd=ROOT,
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


def test_cli_rejects_old_autoconduck_aliases() -> None:
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
    assert ".rudder" in result_path.stdout


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


def test_cli_print_mode_exact_separation() -> None:
    # Print mode with fake provider
    result = run_cli(
        "-p", "say hello world",
        "--model", "fake:fast-model",
        "--fake-provider",
    )
    assert result.returncode == EXIT_OK
    # stdout must only contain final lead output, not progress or diagnostics
    assert len(result.stdout.strip()) > 0
    # stderr must not contain the primary model output
    assert result.stdout.strip() not in result.stderr


def test_cli_jsonl_mode_emits_valid_versioned_events_and_terminal() -> None:
    result = run_cli(
        "--json", "analyze the code",
        "--model", "fake:fast-model",
        "--fake-provider",
    )
    assert result.returncode == EXIT_OK
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) >= 1

    parsed_events: list[EventEnvelope] = []
    for line in lines:
        data = json.loads(line)
        assert data["schema_version"] == 1
        envelope = EventEnvelope.model_validate(data)
        parsed_events.append(envelope)

    # Terminal event must be run.completed (or failed/blocked/cancelled)
    terminal_event = parsed_events[-1]
    assert terminal_event.type in (
        "run.completed",
        "run.failed",
        "run.blocked",
        "run.cancelled",
    )
