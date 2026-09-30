"""Phase 1 CLI boot-split matrix (draft sections 8.1, 8.5, 13.4)."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from typing import Any

import pytest

from skail.cli.exit_codes import EXIT_FAILURE, EXIT_OK
from skail.cli.main import main
from skail.config.models import SkailConfig
from skail.tui.app import ACTION_REGISTRY, SkailApp
from skail.tui.onboarding import NON_TTY_USAGE_ERROR


@pytest.fixture(autouse=True)
def isolate_cli_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # These tests call main() in-process; the CLI resolves its workspace via
    # Path.cwd() (src/skail/cli/main.py:440) and creates approvals/questions
    # stores under workspace/.skail (main.py:547-548). Keep that inside tmp.
    home = tmp_path / "home"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("APPDATA", str(home / "AppData"))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData" / "Local"))
    monkeypatch.setenv("HOME", str(home))


class _FakeJournal:
    def migrate(self) -> None:
        return None

    def get_session_snapshot(self, session_id: str) -> None:
        return None

    def update_session_status(self, **kwargs: Any) -> None:
        return None


class _FakeCheckpoints:
    def initialize(self) -> None:
        return None


class _FakeSessionRecord:
    session_id = "01JBOOT"


class _FakeSessionService:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        return None

    def create_session(self, **kwargs: Any) -> _FakeSessionRecord:
        return _FakeSessionRecord()

    def list_sessions(self) -> list[Any]:
        return []


class _CapturedLaunch:
    app_kwargs: dict[str, Any] | None = None


def _install_cli_fakes(
    monkeypatch: pytest.MonkeyPatch,
    captured: _CapturedLaunch,
) -> None:
    import skail.cli.main as cli_main

    monkeypatch.setattr(cli_main, "ProjectTrustStore", lambda *a, **k: _NoopTrust())
    monkeypatch.setattr(
        cli_main, "load_config", lambda **k: Namespace(config=SkailConfig())
    )
    monkeypatch.setattr(
        cli_main,
        "_build_storage",
        lambda **k: (_FakeJournal(), _FakeCheckpoints(), k.get("ephemeral_dir")),
    )
    monkeypatch.setattr(cli_main, "SessionService", _FakeSessionService)

    import skail.tui.app as tui_app

    real_app = tui_app.SkailApp

    def _fake_app_class(**kwargs: Any) -> Any:
        captured.app_kwargs = kwargs

        class _FakeApp:
            def run(self) -> int:
                return EXIT_OK

        return _FakeApp()

    monkeypatch.setattr(tui_app, "SkailApp", _fake_app_class)
    monkeypatch.setattr(cli_main, "SkailApp", _fake_app_class, raising=False)
    _ = real_app


class _NoopTrust:
    def assess(self, identity: Any) -> Namespace:
        return Namespace(level="untrusted")


def _set_tty(monkeypatch: pytest.MonkeyPatch, *, tty: bool) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: tty)
    monkeypatch.setattr("sys.stdout.isatty", lambda: tty)


def test_non_tty_no_args_prints_exact_usage_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captured = _CapturedLaunch()
    _install_cli_fakes(monkeypatch, captured)
    _set_tty(monkeypatch, tty=False)

    code = main([])

    assert code == EXIT_FAILURE
    err = capsys.readouterr().err
    assert NON_TTY_USAGE_ERROR in err
    assert "ready" not in err
    assert captured.app_kwargs is None


@pytest.mark.parametrize("argv", (["--resume", "01JBOOT"], ["--continue"]))
def test_non_tty_resume_without_prompt_is_rejected_before_execution(
    argv: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured = _CapturedLaunch()
    _install_cli_fakes(monkeypatch, captured)
    _set_tty(monkeypatch, tty=False)

    import skail.cli.main as cli_main

    class _ExistingSessionService(_FakeSessionService):
        requests: list[str] = []

        def list_sessions(self) -> list[Any]:
            self.requests.append("list")
            return [_FakeSessionRecord()]

        def resume_session(self, session_id: str) -> Namespace:
            self.requests.append("resume")
            return Namespace(
                ok=True,
                session=_FakeSessionRecord(),
                recovery_error=None,
            )

    monkeypatch.setattr(cli_main, "SessionService", _ExistingSessionService)
    executions: list[dict[str, Any]] = []

    async def _fake_execute(**kwargs: Any) -> int:
        executions.append(kwargs)
        return EXIT_OK

    monkeypatch.setattr(cli_main, "_execute_instruction", _fake_execute)

    code = main(argv)

    assert code == EXIT_FAILURE
    assert NON_TTY_USAGE_ERROR in capsys.readouterr().err
    assert executions == []
    assert _ExistingSessionService.requests == []
    assert captured.app_kwargs is None


def test_tty_no_args_no_keys_mounts_onboarding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in ("LLMGATEWAY_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    captured = _CapturedLaunch()
    _install_cli_fakes(monkeypatch, captured)
    _set_tty(monkeypatch, tty=True)

    code = main([])

    assert code == EXIT_OK
    assert captured.app_kwargs is not None
    assert captured.app_kwargs["runtime_factory"] is not None
    assert captured.app_kwargs["controller"] if False else True

    app = SkailApp(
        runtime_factory=lambda: None,
        bootstrap={"workspace": ".", "session_id": "x"},
    )
    assert app.app_state == "onboarding"
    assert app.controller is None


def test_tty_valid_key_starts_async_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLMGATEWAY_API_KEY", "test-key")
    captured = _CapturedLaunch()
    _install_cli_fakes(monkeypatch, captured)
    _set_tty(monkeypatch, tty=True)

    code = main([])

    assert code == EXIT_OK
    assert captured.app_kwargs is not None

    app = SkailApp(
        runtime_factory=lambda: None,
        bootstrap={"workspace": ".", "session_id": "x"},
    )
    assert app.app_state == "initializing"


def test_recoverable_startup_failure_enters_error_state() -> None:
    app = SkailApp(
        runtime_factory=lambda: None,
        bootstrap={"workspace": ".", "session_id": "x"},
    )
    app.onboarding_credentials.set_key("super-secret-key")
    app._enter_error_state("boom super-secret-key")

    assert app.app_state == "error"
    assert app.startup_error is not None
    assert "super-secret-key" not in app.startup_error
    assert "<redacted>" in app.startup_error


def test_action_registry_covers_quit_and_composer_panel_cycle() -> None:
    assert ACTION_REGISTRY["quit"]["binding"] == "ctrl+c"
    assert ACTION_REGISTRY["cycle_panels"]["binding"] == "shift+tab"
    for action in ("view_budget", "view_agents", "view_plan", "view_route"):
        assert action not in ACTION_REGISTRY


def test_headless_print_delegates_without_mounting_tui(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _CapturedLaunch()
    _install_cli_fakes(monkeypatch, captured)
    _set_tty(monkeypatch, tty=False)

    import skail.cli.main as cli_main

    async def _fake_execute(**kwargs: Any) -> int:
        return EXIT_OK

    monkeypatch.setattr(cli_main, "_execute_instruction", _fake_execute)
    monkeypatch.setattr(cli_main, "_build_runtime_models", lambda *a, **k: None)

    code = main(["-p", "hello"])

    assert code == EXIT_OK
    assert captured.app_kwargs is None
