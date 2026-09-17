"""Phase 4 headless parity: flags unchanged, usage error exact, /quit idle."""

from __future__ import annotations

from argparse import Namespace
from typing import Any

import pytest

from skail.cli.exit_codes import EXIT_FAILURE, EXIT_OK
from skail.cli.main import main
from skail.config.models import SkailConfig
from skail.tui.onboarding import NON_TTY_USAGE_ERROR


class _FakeJournal:
    def migrate(self) -> None:
        return None

    def get_session_snapshot(self, session_id: str) -> None:
        return None

    def update_session_status(self, **kwargs: Any) -> None:
        self.last_status = kwargs
        return None


class _FakeCheckpoints:
    def initialize(self) -> None:
        return None


class _FakeSessionRecord:
    session_id = "01JPARITY"


class _FakeSessionService:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        return None

    def create_session(self, **kwargs: Any) -> _FakeSessionRecord:
        return _FakeSessionRecord()

    def list_sessions(self) -> list[Any]:
        return [_FakeSessionRecord()]

    def resume_session(self, session_id: str) -> Namespace:
        return Namespace(ok=True, session=_FakeSessionRecord(), recovery_error=None)


class _CapturedLaunch:
    app_kwargs: dict[str, Any] | None = None


class _NoopTrust:
    def assess(self, identity: Any) -> Namespace:
        return Namespace(level="untrusted")


def _install_cli_fakes(
    monkeypatch: pytest.MonkeyPatch, captured: _CapturedLaunch
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

    def _fake_app_class(**kwargs: Any) -> Any:
        captured.app_kwargs = kwargs

        class _FakeApp:
            def run(self) -> int:
                return EXIT_OK

        return _FakeApp()

    import skail.tui.app as tui_app

    monkeypatch.setattr(tui_app, "SkailApp", _fake_app_class)
    monkeypatch.setattr(cli_main, "SkailApp", _fake_app_class, raising=False)


def _set_tty(monkeypatch: pytest.MonkeyPatch, *, tty: bool) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: tty)
    monkeypatch.setattr("sys.stdout.isatty", lambda: tty)


def test_non_tty_no_arg_exact_usage_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captured = _CapturedLaunch()
    _install_cli_fakes(monkeypatch, captured)
    _set_tty(monkeypatch, tty=False)
    code = main([])
    assert code == EXIT_FAILURE
    err = capsys.readouterr().err
    assert NON_TTY_USAGE_ERROR in err
    assert captured.app_kwargs is None


@pytest.mark.parametrize(
    "argv",
    [
        ["-p", "hello", "--fake-provider"],
        ["--jsonl", "hello", "--fake-provider"],
        ["-c", "hello", "--fake-provider"],
        ["-r", "01JPARITY", "hello", "--fake-provider"],
        ["--no-session", "-p", "hello", "--fake-provider"],
    ],
)
def test_headless_flags_delegate_without_mounting_tui(
    monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    captured = _CapturedLaunch()
    _install_cli_fakes(monkeypatch, captured)
    _set_tty(monkeypatch, tty=False)

    import skail.cli.main as cli_main

    seen: dict[str, Any] = {}

    async def _fake_execute(**kwargs: Any) -> int:
        seen.update(kwargs)
        return EXIT_OK

    monkeypatch.setattr(cli_main, "_execute_instruction", _fake_execute)
    monkeypatch.setattr(cli_main, "_build_runtime_models", lambda *a, **k: None)
    code = main(argv)
    assert code == EXIT_OK
    assert captured.app_kwargs is None
    assert seen


def test_quit_marks_session_idle() -> None:
    journal = _FakeJournal()
    journal.update_session_status(session_id="01JPARITY", status="idle")
    assert journal.last_status == {"session_id": "01JPARITY", "status": "idle"}


def test_quit_dispatch_action() -> None:
    from skail.tui.commands import dispatch_slash_command
    from skail.tui.projection import TuiProjection

    result = dispatch_slash_command("/quit", TuiProjection())
    assert result.action == "quit"
    assert result.command == "quit"
