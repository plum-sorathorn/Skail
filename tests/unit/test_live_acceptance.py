from __future__ import annotations

import json
import os
import queue
import sqlite3
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from scripts.live_acceptance import (
    KEYS,
    InteractionStep,
    LiveSpec,
    PTYSession,
    ScreenCapture,
    _catalog_preflight,
    _finish_campaign,
    _require_file_absent,
    _reserve_campaign,
    _verify_workspace_expectations,
    find_latest_run,
    find_started_provider_call,
    read_to_eof,
    validate_spec,
    verify_session_export,
    write_user_config,
)


class _BufferedProcess:
    def __init__(self) -> None:
        self.chunks = ["before-exit", "after-exit", ""]
        self.read_count = 0

    def read(self, size: int) -> str:
        assert size > 0
        self.read_count += 1
        return self.chunks.pop(0)

    def isalive(self) -> bool:
        return self.read_count < 2


def _profile() -> dict[str, object]:
    return {
        "provider": "llmgateway",
        "model": "gpt-4.1-mini",
        "source": "user",
        "as_of": "2026-09-29T17:33:51.596092Z",
        "trusted": True,
        "provenance": "Reviewed profile; scores are routing estimates.",
        "fields": {
            "capability": {
                "coding": 0.316,
                "reasoning": 0.65,
                "tool_reliability": 0.66,
                "latency": 0.031,
            }
        },
    }


def test_reader_drains_final_pty_buffer_after_child_exits() -> None:
    process = _BufferedProcess()
    chunks: list[str] = []

    read_to_eof(process, chunks.append)

    assert chunks == ["before-exit", "after-exit"]


def test_inflight_probe_matches_only_a_started_call_for_the_selected_model(
    tmp_path: Path,
) -> None:
    journal_path = tmp_path / "journal.sqlite"
    with sqlite3.connect(journal_path) as connection:
        connection.executescript(
            "CREATE TABLE runs(run_id TEXT, status TEXT);"
            "CREATE TABLE tasks(task_id TEXT, run_id TEXT);"
            "CREATE TABLE attempts(attempt_id TEXT, task_id TEXT);"
            "CREATE TABLE assignments(assignment_id TEXT, attempt_id TEXT, "
            "provider TEXT, model TEXT);"
            "CREATE TABLE provider_calls(call_id TEXT, assignment_id TEXT, status TEXT, "
            "created_at TEXT, updated_at TEXT);"
            "INSERT INTO runs VALUES ('run-1', 'running');"
            "INSERT INTO tasks VALUES ('task-1', 'run-1');"
            "INSERT INTO attempts VALUES ('attempt-1', 'task-1');"
            "INSERT INTO assignments VALUES "
            "('assignment-1', 'attempt-1', 'llmgateway', 'gpt-5-mini');"
            "INSERT INTO provider_calls VALUES ('call-1', 'assignment-1', 'started', 't1', 't1');"
        )

    call = find_started_provider_call(journal_path, "llmgateway:gpt-5-mini")

    assert call == {
        "call_id": "call-1",
        "provider": "llmgateway",
        "model": "gpt-5-mini",
        "status": "started",
        "created_at": "t1",
        "updated_at": "t1",
    }
    with sqlite3.connect(journal_path) as connection:
        connection.execute("UPDATE provider_calls SET status='completed'")
    assert find_started_provider_call(journal_path, "llmgateway:gpt-5-mini") is None


def test_latest_run_probe_returns_committed_status_and_session_run_count(tmp_path: Path) -> None:
    journal_path = tmp_path / "journal.sqlite"
    with sqlite3.connect(journal_path) as connection:
        connection.executescript(
            "CREATE TABLE sessions(session_id TEXT, status TEXT);"
            "CREATE TABLE runs(run_id TEXT, session_id TEXT, status TEXT, created_at TEXT);"
            "INSERT INTO sessions VALUES ('session-1', 'idle');"
            "INSERT INTO runs VALUES "
            "('run-1', 'session-1', 'blocked', '2026-10-01T00:00:00Z');"
            "INSERT INTO runs VALUES "
            "('run-2', 'session-1', 'completed', '2026-10-01T00:00:01Z');"
        )

    assert find_latest_run(journal_path) == {
        "run_id": "run-2",
        "status": "completed",
        "session_status": "idle",
        "run_count": 2,
    }


def test_screen_capture_reconstructs_terminal_cells() -> None:
    capture = ScreenCapture(columns=30, rows=5)
    capture.feed("before\x1b[2;4Hfinal answer")

    assert "before" in capture.text
    assert "final answer" in capture.text


def test_live_driver_help_runs_from_an_external_working_directory(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts" / "live_acceptance.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert completed.returncode == 0
    assert "--campaign-ledger" in completed.stdout


def test_live_spec_requires_argv_and_workspace_outside_the_checkout(tmp_path: Path) -> None:
    workspace = tmp_path / "fixture"
    workspace.mkdir()
    spec = {
        "scenario_id": "r9-question-freeform",
        "argv": ["python", "-m", "skail", "--budget", "0.40"],
        "workspace": str(workspace),
        "budget_usd": "0.40",
        "campaign_reserve_usd": "0.40",
        "selected_models": ["llmgateway:gpt-4.1-mini"],
        "lead_model": "llmgateway:gpt-4.1-mini",
        "capability_profiles": [_profile()],
        "steps": [
            {"wait_for": "QUESTION · Your answer is needed"},
            {"send_text": "Use the harmless fixture only."},
            {"key": "enter"},
        ],
    }

    parsed = validate_spec(spec, root=Path(__file__).resolve().parents[2])

    assert parsed.workspace == workspace.resolve()
    assert parsed.argv == ("python", "-m", "skail", "--budget", "0.40")
    assert parsed.budget_usd == Decimal("0.40")
    assert len(parsed.steps) == 3


def test_live_spec_rejects_shell_strings_overspend_and_unowned_workspace(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    base = {
        "scenario_id": "r9-first-attempt",
        "argv": "python -m skail",
        "workspace": str(fixture),
        "budget_usd": "3.01",
        "campaign_reserve_usd": "3.01",
        "selected_models": ["llmgateway:gpt-4.1-mini"],
        "lead_model": "llmgateway:gpt-4.1-mini",
        "capability_profiles": [_profile()],
        "steps": [{"key": "enter"}],
    }

    with pytest.raises(ValueError, match="argv"):
        validate_spec(base, root=Path(__file__).resolve().parents[2])

    base["argv"] = ["python", "-m", "skail", "--budget", "3.01"]
    with pytest.raises(ValueError, match="campaign cap"):
        validate_spec(base, root=Path(__file__).resolve().parents[2])

    base["budget_usd"] = "0.40"
    base["campaign_reserve_usd"] = "0.40"
    base["argv"] = [
        "python",
        "-m",
        "skail",
        "--budget",
        "0.40",
        "--agent-model",
        "explorer=llmgateway:gpt-5-mini",
    ]
    with pytest.raises(ValueError, match="members of selected_models"):
        validate_spec(base, root=Path(__file__).resolve().parents[2])

    fake_root = tmp_path / "repo"
    fake_root.mkdir()
    checkout_workspace = fake_root / "out" / "live-fixture"
    checkout_workspace.mkdir(parents=True, exist_ok=True)
    base["workspace"] = str(checkout_workspace)
    base["argv"] = ["python", "-m", "skail", "--budget", "0.40"]
    with pytest.raises(ValueError, match="outside the source checkout"):
        validate_spec(base, root=fake_root)


@pytest.mark.parametrize("status", ("failed", "captured"))
def test_campaign_reservations_count_unsettled_attempts_toward_the_cap(
    tmp_path: Path, status: str
) -> None:
    workspace = tmp_path / "fixture"
    workspace.mkdir()
    evidence = tmp_path / "evidence"
    ledger = tmp_path / "campaign.json"
    first = validate_spec(
        {
            "scenario_id": "attempt-one",
            "argv": ["python", "-m", "skail", "--budget", "0.15"],
            "workspace": str(workspace),
            "budget_usd": "0.15",
            "campaign_reserve_usd": "0.40",
            "selected_models": ["llmgateway:gpt-4.1-mini"],
            "lead_model": "llmgateway:gpt-4.1-mini",
            "capability_profiles": [_profile()],
            "steps": [{"key": "ctrl+c"}],
        },
        root=tmp_path / "repo",
    )
    second = validate_spec(
        {
            "scenario_id": "attempt-two",
            "argv": ["python", "-m", "skail", "--budget", "0.15"],
            "workspace": str(workspace),
            "budget_usd": "0.15",
            "campaign_reserve_usd": "2.61",
            "selected_models": ["llmgateway:gpt-4.1-mini"],
            "lead_model": "llmgateway:gpt-4.1-mini",
            "capability_profiles": [_profile()],
            "steps": [{"key": "ctrl+c"}],
        },
        root=tmp_path / "repo",
    )

    _reserve_campaign(ledger, first, evidence)
    _finish_campaign(ledger, first.scenario_id, status)

    with pytest.raises(ValueError, match="approved USD 3.00 campaign cap"):
        _reserve_campaign(ledger, second, evidence)


def test_campaign_settles_only_verified_local_cost_before_releasing_reservation(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "fixture"
    workspace.mkdir()
    evidence = tmp_path / "evidence"
    ledger = tmp_path / "campaign.json"
    spec = validate_spec(
        {
            "scenario_id": "settled-attempt",
            "argv": ["python", "-m", "skail", "--budget", "0.15"],
            "workspace": str(workspace),
            "budget_usd": "0.15",
            "campaign_reserve_usd": "0.40",
            "selected_models": ["llmgateway:gpt-4.1-mini"],
            "lead_model": "llmgateway:gpt-4.1-mini",
            "capability_profiles": [_profile()],
            "steps": [{"key": "ctrl+c"}],
        },
        root=tmp_path / "repo",
    )
    following = validate_spec(
        {
            "scenario_id": "remaining-allocation",
            "argv": ["python", "-m", "skail", "--budget", "0.15"],
            "workspace": str(workspace),
            "budget_usd": "0.15",
            "campaign_reserve_usd": "2.99",
            "selected_models": ["llmgateway:gpt-4.1-mini"],
            "lead_model": "llmgateway:gpt-4.1-mini",
            "capability_profiles": [_profile()],
            "steps": [{"key": "ctrl+c"}],
        },
        root=tmp_path / "repo",
    )

    _reserve_campaign(ledger, spec, evidence)
    _finish_campaign(ledger, spec.scenario_id, "failed", Decimal("0.01"))
    _reserve_campaign(ledger, following, evidence)

    assert json.loads(ledger.read_text(encoding="utf-8"))["runs"][0]["settled_usd"] == "0.01"


def test_live_user_config_contains_only_selected_models_and_reviewed_profiles(
    tmp_path: Path,
) -> None:
    profile = {
        "provider": "llmgateway",
        "model": "gpt-4.1-mini",
        "source": "user",
        "as_of": "2026-09-29T17:33:51.596092Z",
        "trusted": True,
        "provenance": "Reviewed profile; capability scores are routing estimates.",
        "fields": {
            "capability": {
                "coding": 0.316,
                "reasoning": 0.65,
                "tool_reliability": 0.66,
                "latency": 0.031,
            }
        },
    }
    spec = LiveSpec(
        scenario_id="config-contract",
        argv=("python", "-m", "skail", "--budget", "0.40"),
        workspace=tmp_path,
        budget_usd=Decimal("0.40"),
        campaign_reserve_usd=Decimal("0.40"),
        selected_models=("llmgateway:gpt-4.1-mini",),
        lead_model="llmgateway:gpt-4.1-mini",
        capability_profiles=(profile,),
        steps=(InteractionStep("key", "enter"),),
        env={},
    )

    config_path = write_user_config(tmp_path / "isolated-home", spec)

    from skail.config.loader import load_config

    config = load_config(user_path=config_path, project_trusted=False).config
    assert config.providers["llmgateway"].models == ("gpt-4.1-mini",)
    assert config.routing.lead_model == "llmgateway:gpt-4.1-mini"
    assert config.budget.run_usd == Decimal("0.40")
    assert config.catalog.entries[0].trusted is True
    assert "LLMGATEWAY_API_KEY" in config.providers["llmgateway"].api_key_env
    assert "live-secret" not in config_path.read_text(encoding="utf-8")


def test_catalog_preflight_uses_only_authenticated_selected_models(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "fixture"
    workspace.mkdir()
    spec = validate_spec(
        {
            "scenario_id": "catalog-check",
            "argv": ["python", "-m", "skail", "--budget", "0.40"],
            "workspace": str(workspace),
            "budget_usd": "0.40",
            "campaign_reserve_usd": "0.40",
            "selected_models": ["llmgateway:gpt-4.1-mini"],
            "lead_model": "llmgateway:gpt-4.1-mini",
            "capability_profiles": [_profile()],
            "steps": [{"key": "enter"}],
        },
        root=tmp_path / "repo",
    )
    response = type(
        "Response",
        (),
        {
            "is_success": True,
            "status_code": 200,
            "json": lambda self: {
                "data": [
                    {
                        "id": "gpt-4.1-mini",
                        "pricing": {"prompt": "0.4e-6", "completion": "1.6e-6"},
                        "providers": [{"tools": True}],
                    },
                    {"id": "unselected-model"},
                ]
            },
        },
    )()
    monkeypatch.setattr("scripts.live_acceptance.httpx.get", lambda *args, **kwargs: response)
    evidence = tmp_path / "evidence"
    evidence.mkdir()

    result = _catalog_preflight({"LLMGATEWAY_API_KEY": "catalog-secret"}, spec, evidence)

    assert result["accessible_model_count"] == 2
    assert result["selected_models"] == ["llmgateway:gpt-4.1-mini"]
    saved = (evidence / "catalog-preflight.json").read_text(encoding="utf-8")
    assert "catalog-secret" not in saved
    assert "unselected-model" not in saved


def test_session_export_verifier_counts_all_completion_events_and_real_question_events() -> None:
    export = {
        "schema_version": 2,
        "runs": [{"run_id": "run-1", "status": "completed"}],
        "tasks": [{"task_id": "task-1"}],
        "attempts": [{"task_id": "task-1", "attempt_id": "attempt-1"}],
        "events": [
            {
                "event_id": "event-q",
                "run_id": "run-1",
                "type": "user.question",
                "payload": {"interrupt_id": "question-1", "options": []},
            },
            {
                "event_id": "event-a",
                "run_id": "run-1",
                "type": "user.answer",
                "payload": {"interrupt_id": "question-1"},
            },
            {
                "event_id": "event-c1",
                "run_id": "run-1",
                "type": "run.completed",
                "payload": {"output": "Complete answer."},
            },
            {
                "event_id": "event-c2",
                "run_id": "run-1",
                "type": "run.completed",
                "payload": {"output": "Complete answer."},
            },
        ],
        "provider_calls": [
            {
                "call_id": "call-1",
                "run_id": "run-1",
                "provider": "llmgateway",
                "model": "gpt-4.1-mini",
                "cost_usd": "0.001",
            }
        ],
    }

    result = verify_session_export(
        export,
        terminal_frames=["Final answer: Complete answer."],
        selected_models=("llmgateway:gpt-4.1-mini",),
        reserved_usd=Decimal("0.40"),
        expected_event_counts={"user.question": 1, "user.answer": 1, "user.cancellation": 0},
        expected_run_status_counts={"completed": 1},
        expected_question_kind="free_form",
    )

    assert result["event_counts"]["user.question"] == 1
    assert result["event_counts"]["user.answer"] == 1
    assert "user.prompt" not in result["event_counts"]
    assert result["completion_counts"] == {"run-1": 2}
    assert result["duplicate_completion_run_ids"] == ["run-1"]
    assert result["terminal_answer_matches"] == {"run-1": True}
    assert result["local_token_cost_usd"] == "0.001"
    assert result["event_count_mismatches"] == {}
    assert result["run_status_count_mismatches"] == {}


def test_session_export_verifier_rejects_a_partial_terminal_answer() -> None:
    export = {
        "schema_version": 2,
        "runs": [{"run_id": "run-1", "status": "completed"}],
        "tasks": [],
        "attempts": [],
        "events": [
            {
                "event_id": "event-c1",
                "run_id": "run-1",
                "type": "run.completed",
                "payload": {"output": "Complete answer with several important words."},
            }
        ],
        "provider_calls": [],
    }

    result = verify_session_export(
        export,
        terminal_frames=["Complete answer with several"],
        selected_models=("llmgateway:gpt-4.1-mini",),
        reserved_usd=Decimal("0.40"),
    )

    assert result["terminal_answer_matches"] == {"run-1": False}


def test_session_export_verifier_skips_rendering_for_action_only_runs() -> None:
    export = {
        "schema_version": 2,
        "runs": [{"run_id": "run-1", "status": "completed"}],
        "tasks": [],
        "attempts": [],
        "events": [
            {
                "event_id": "event-c1",
                "run_id": "run-1",
                "type": "run.completed",
                "payload": {"output": '{"status":"success","summary":"action result"}'},
            }
        ],
        "provider_calls": [],
    }

    result = verify_session_export(
        export,
        terminal_frames=["The operation completed; nothing was rendered."],
        selected_models=("llmgateway:gpt-4.1-mini",),
        reserved_usd=Decimal("0.40"),
        expected_run_status_counts={"completed": 1},
        terminal_answer_required=False,
    )

    assert result["terminal_answer_matches"] == {"run-1": None}
    assert result["status"] == "passed"


def test_session_export_verifier_detects_provider_start_after_run_cancellation() -> None:
    export = {
        "schema_version": 2,
        "runs": [{"run_id": "run-1", "status": "cancelled"}],
        "tasks": [],
        "attempts": [],
        "events": [
            {"event_id": "cancel", "run_id": "run-1", "sequence": 4, "type": "run.cancelled"},
            {"event_id": "late-start", "run_id": "run-1", "sequence": 5, "type": "model.started"},
        ],
        "provider_calls": [],
    }

    result = verify_session_export(
        export,
        terminal_frames=[],
        selected_models=("llmgateway:gpt-4.1-mini",),
        reserved_usd=Decimal("0.24"),
        expected_run_status_counts={"cancelled": 1},
    )

    assert result["model_started_after_cancel"] == ["run-1"]
    assert "model_started_after_cancel" in result["failed_checks"]


def test_cancelled_live_call_passes_only_with_its_budget_reservation_held() -> None:
    export = {
        "schema_version": 2,
        "runs": [{"run_id": "run-1", "status": "cancelled"}],
        "tasks": [{"task_id": "lead"}, {"task_id": "child"}],
        "attempts": [],
        "events": [
            {"event_id": "started", "run_id": "run-1", "sequence": 1, "type": "model.started"},
            {"event_id": "cancel", "run_id": "run-1", "sequence": 2, "type": "run.cancelled"},
        ],
        "provider_calls": [
            {
                "call_id": "child-call",
                "assignment_id": "child-assignment",
                "run_id": "run-1",
                "provider": "llmgateway",
                "model": "gpt-5-mini",
                "status": "ambiguous",
                "authority": "unknown",
                "cost_usd": None,
            }
        ],
        "budget_reservations": [
            {
                "idempotency_key": "assignment-reservation:child-assignment",
                "status": "reserved",
                "amount_usd": "0.017471",
            }
        ],
        "usage": [],
    }
    kwargs = {
        "terminal_frames": ["QUEUED 1\nApplication shutdown: 1 queued prompt discarded."],
        "selected_models": ("llmgateway:gpt-5-mini",),
        "reserved_usd": Decimal("0.49"),
        "expected_run_status_counts": {"cancelled": 1},
        "expected_run_count": 1,
        "expected_task_count": 2,
        "observed_provider_call_ids": ("child-call",),
        "expected_held_ambiguous": True,
        "expected_terminal_text": ("Application shutdown: 1 queued prompt discarded.",),
    }

    result = verify_session_export(export, **kwargs)

    assert result["status"] == "passed"
    assert result["accounting_disposition"] == "held_ambiguous"
    assert result["local_token_cost_usd"] is None
    assert result["held_reservation_usd"] == "0.017471"

    export["budget_reservations"][0]["status"] = "released"
    released = verify_session_export(export, **kwargs)
    assert released["status"] == "failed"
    assert "held_ambiguous_accounting_missing" in released["failed_checks"]

    export["budget_reservations"][0]["status"] = "reserved"
    missing_queue = verify_session_export(
        export, **{**kwargs, "terminal_frames": ["QUEUED 1"]}
    )
    assert "terminal_text_missing" in missing_queue["failed_checks"]

    unobserved = verify_session_export(
        export, **{**kwargs, "observed_provider_call_ids": ()}
    )
    assert "held_ambiguous_accounting_missing" in unobserved["failed_checks"]

    ordinary = verify_session_export(export, **{**kwargs, "expected_held_ambiguous": False})
    assert "cost_unresolved_or_over_reservation" in ordinary["failed_checks"]

    export["runs"].append({"run_id": "unexpected-follow-up", "status": "completed"})
    extra_run = verify_session_export(export, **kwargs)
    assert "run_count_mismatch" in extra_run["failed_checks"]


def test_workspace_verifier_checks_full_path_set_and_expected_marker(tmp_path: Path) -> None:
    workspace = tmp_path / "fixture"
    workspace.mkdir()
    marker = workspace / "approved-marker.txt"
    marker.write_text("approved once\n", encoding="utf-8")
    before = {"before.txt": "old-hash"}
    after = {"before.txt": "old-hash", "approved-marker.txt": "marker-hash"}

    result = _verify_workspace_expectations(
        workspace,
        before,
        after,
        {
            "changed_paths": ["approved-marker.txt"],
            "file_contents": {"approved-marker.txt": "approved once\n"},
        },
    )

    assert result["status"] == "passed"
    assert result["changed_paths"] == ["approved-marker.txt"]
    assert result["file_content_matches"] == {"approved-marker.txt": True}


def test_file_absence_precondition_rejects_an_existing_marker(tmp_path: Path) -> None:
    (tmp_path / "marker.txt").write_text("already present", encoding="utf-8")

    with pytest.raises(RuntimeError, match="before approval"):
        _require_file_absent(tmp_path, "marker.txt")


def test_windows_pty_captures_tty_dimensions_and_ctrl_enter(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("Windows PTY contract")
    pytest.importorskip("winpty")
    probe = """import os, sys
from textual.app import App
from textual.widgets import Static

class Probe(App):
    def compose(self):
        size = os.get_terminal_size()
        ready = (
            f"READY TTY={sys.stdin.isatty()} "
            f"SIZE={size.columns}x{size.lines}"
        )
        yield Static(ready, id="probe")

    def on_key(self, event):
        if event.key == "ctrl+enter":
            self.query_one("#probe", Static).update("CTRLENTER")
            event.stop()

Probe().run()
"""
    spec = LiveSpec(
        scenario_id="pty-contract",
        argv=(sys.executable, "-u", "-c", probe),
        workspace=tmp_path,
        budget_usd=Decimal("0.01"),
        campaign_reserve_usd=Decimal("0.01"),
        selected_models=("llmgateway:gpt-4.1-mini",),
        lead_model="llmgateway:gpt-4.1-mini",
        capability_profiles=(_profile(),),
        steps=(InteractionStep("wait_for", r"TTY=True SIZE=80x24", 10),),
        env={},
    )
    session = PTYSession(spec, os.environ.copy())
    try:
        screen = session.wait_for(r"READY TTY=True SIZE=80x24", 10)
        session.send_key("ctrl+enter")
        screen = session.wait_for("CTRLENTER", 5)
    finally:
        session.close()

    assert "CTRLENTER" in screen


def test_pty_cleanup_asks_the_owned_app_to_quit_before_forcing_exit() -> None:
    session = PTYSession.__new__(PTYSession)
    session.capture = ScreenCapture(columns=80, rows=24)
    session._chunks = queue.Queue()
    session._eof = False

    class Process:
        alive = True
        writes: list[str] = []
        forced = False

        def isalive(self) -> bool:
            return self.alive

        def write(self, value: str) -> None:
            self.writes.append(value)
            self.alive = False
            session._chunks.put(None)

        def terminate(self, *, force: bool) -> None:
            self.forced = force
            self.alive = False
            session._chunks.put(None)

    class Reader:
        def join(self, timeout: float) -> None:
            del timeout

    session.process = Process()
    session._reader = Reader()

    session.close(graceful=True)

    assert session.process.writes == [KEYS["ctrl+c"]]
    assert session.process.forced is False
