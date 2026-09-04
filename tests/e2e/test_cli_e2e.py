from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from rudder.cli.exit_codes import EXIT_BLOCKED, EXIT_FAILURE, EXIT_OK, EXIT_USAGE
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


def test_cli_jsonl_primary_flag_emits_valid_versioned_events() -> None:
    result = run_cli(
        "--jsonl", "analyze the code",
        "--model", "fake:fast-model",
        "--fake-provider",
    )
    assert result.returncode == EXIT_OK
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) >= 1

    parsed_events: list[EventEnvelope] = [
        EventEnvelope.model_validate(json.loads(line)) for line in lines
    ]
    assert parsed_events[0].type == "run.started"
    assert "model.started" in [event.type for event in parsed_events]
    assert "model.completed" in [event.type for event in parsed_events]
    assert parsed_events[-1].type == "run.completed"


def test_cli_single_run_id_across_streamed_events() -> None:
    result = run_cli(
        "--jsonl", "run inspection",
        "--model", "fake:fast-model",
        "--fake-provider",
    )
    assert result.returncode == EXIT_OK
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    parsed_events = [EventEnvelope.model_validate(json.loads(line)) for line in lines]
    assert len(parsed_events) >= 2

    # Every event must share the exact same run_id
    first_run_id = parsed_events[0].run_id
    assert all(event.run_id == first_run_id for event in parsed_events)

    # Sequences must be strictly increasing
    sequences = [event.sequence for event in parsed_events]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)


def test_cli_normal_mode_without_fake_provider_fails_when_no_credentials() -> None:
    import os

    clean_env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "USERPROFILE": os.environ.get("USERPROFILE", ""),
        "APPDATA": os.environ.get("APPDATA", ""),
        "LOCALAPPDATA": os.environ.get("LOCALAPPDATA", ""),
    }
    result = run_cli(
        "-p", "say hello without fake provider",
        env=clean_env,
    )
    assert result.returncode == EXIT_FAILURE
    assert (
        "credentials" in result.stderr.lower()
        or "provider" in result.stderr.lower()
    )


def test_cli_budget_denial_returns_blocked_exit_code() -> None:
    result = run_cli(
        "-p",
        "do not launch unaffordable work",
        "--fake-provider",
        "--budget",
        "0.001",
    )

    assert result.returncode == EXIT_BLOCKED
    assert "budget" in result.stderr.lower()


def test_cli_returns_blocked_exit_code_on_interrupted_run(tmp_path: Path) -> None:
    import argparse
    import asyncio

    import rudder.cli.main as cli_main
    from rudder.cli.main import RuntimeModelSet, _execute_instruction
    from rudder.providers.fake import FakeProviderAdapter
    from rudder.runtime.interrupts import QuestionStore
    from rudder.runtime.redaction import RedactionRegistry
    from rudder.sessions.checkpoints import CheckpointStore
    from rudder.sessions.journal import Journal
    from rudder.sessions.service import SessionService
    from rudder.tools.approvals import ApprovalStore
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
        fake_provider=True,
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
            {"fake": FakeProviderAdapter(model)},
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
