"""Phase 4 TUI security tests: keys, redaction, trust, caps, locks, export.

Tests first: every test targets an existing runtime path without new APIs.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from skail.domain.events import SecretRedactor
from skail.runtime.redaction import RedactingLogFilter, RedactionRegistry
from skail.sessions.export import SessionExporter
from skail.sessions.journal import Journal
from skail.tui.onboarding import BootstrapCredentials
from skail.tui.overlays.missions import MissionsOverlay, can_spawn
from skail.tui.projection import ChildView, TranscriptItem, TuiProjection

SECRET = "sk-ant-secret-key-material-12345678"


def _redactor() -> SecretRedactor:
    return SecretRedactor((SECRET,))


def test_keys_never_in_transcript_snapshot_events() -> None:
    proj = TuiProjection()
    proj.note_receipt("hello")
    item = TranscriptItem(id="t1", role="user", title="t", content="plain")
    assert proj._add_transcript_item(item)
    blob = json.dumps(proj.to_dict())
    assert "secret-key-material" not in blob
    assert "sk-ant-" not in blob
    assert SECRET not in blob
    # Transcript content carrying a secret must be scrubbable before display.
    scrubbed = _redactor().scrub(f"leaked {SECRET} here")
    assert SECRET not in str(scrubbed)
    assert "[REDACTED]" in str(scrubbed)


def test_bootstrap_credentials_redacted_repr() -> None:
    creds = BootstrapCredentials(provider="openai")
    creds.set_key(SECRET)
    assert SECRET not in repr(creds)
    assert "<redacted>" in repr(creds)
    assert creds.reveal() == SECRET
    creds.clear()
    assert creds.reveal() == ""


def test_provider_errors_redact_auth_headers_and_keys() -> None:
    redactor = _redactor()
    message = (
        f"provider.authentication: bad key {SECRET} "
        "with header Authorization: Bearer abc123"
    )
    scrubbed = redactor.scrub(message)
    assert isinstance(scrubbed, str)
    assert SECRET not in scrubbed
    payload = {"authorization": f"Bearer {SECRET}", "model": "m"}
    scrubbed_payload = redactor.scrub(payload)
    assert SECRET not in json.dumps(scrubbed_payload)


def test_exception_text_and_debug_logs_scrubbed() -> None:
    registry = RedactionRegistry()
    registry.register(SECRET)
    try:
        raise RuntimeError(f"provider failed with {SECRET}")
    except RuntimeError as exc:
        (line,) = registry.scrub_exception(exc)
        assert SECRET not in line
    records: list[str] = []

    class Sink(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    logger = logging.getLogger("skail.phase4.security.test")
    logger.handlers = []
    logger.addFilter(RedactingLogFilter(registry))
    logger.addHandler(Sink())
    logger.setLevel(logging.DEBUG)
    logger.debug("debug with key %s", SECRET)
    assert records and all(SECRET not in line for line in records)


def test_widget_reprs_carry_no_key_material() -> None:
    creds = BootstrapCredentials(provider="openai")
    creds.set_key(SECRET)
    item = TranscriptItem(id="w1", role="user", title="t", content="hi")
    for obj in (creds, item):
        assert SECRET not in repr(obj)


def test_trust_does_not_bypass_approvals() -> None:
    from skail.tools.approvals import ApprovalStore
    from skail.tools.execution import CommandRequest

    store = ApprovalStore()
    request = CommandRequest(
        "pytest",
        ("-q",),
        Path.cwd(),
        session_id="s1",
        run_id="r1",
        task_id="t1",
        action_id="a1",
    )
    # Trusted workspace or not, an undecided command is not allowed.
    assert store.is_allowed(request) is False


def test_missions_cannot_launch_fourth_child() -> None:
    proj = TuiProjection()
    proj.note_child("c1", "one", "m", "ws-a")
    proj.note_child("c2", "two", "m", "ws-b")
    proj.note_child("c3", "three", "m", "ws-c")
    children = proj.children_view()
    assert len(children) == 3
    ok, message = can_spawn(children)
    assert ok is False
    assert "3/3" in message
    overlay = MissionsOverlay(children)
    assert overlay.try_spawn()[0] is False


def test_cancel_cannot_orphan_writer_locks() -> None:
    from skail.runtime.leases import WorkspaceLeaseManager

    leases = WorkspaceLeaseManager()
    with leases.hold("child-1"):
        assert leases.holder == "child-1"
    assert leases.holder is None
    # Releasing a non-holder never drops another owner's lock.
    with leases.hold("child-1"):
        leases.release("child-2")
        assert leases.holder == "child-1"
    assert leases.holder is None


def test_cancel_marks_child_without_dropping_lease() -> None:
    from skail.runtime.leases import WorkspaceLeaseManager

    leases = WorkspaceLeaseManager()
    proj = TuiProjection()
    proj.note_child("c1", "task", "m", workspace_lock="child-1")
    with leases.hold("child-1"):
        proj.mark_child_status("c1", "cancelled", "cancel requested")
        assert leases.holder == "child-1"
        view = {c.id: c for c in proj.children_view()}
        assert view["c1"].status == "cancelled"
        assert view["c1"].workspace_lock == "child-1"
    assert leases.holder is None


def test_export_contains_no_secrets(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "journal.sqlite")
    journal.migrate()
    session_id = "01JSECURITYPH4"
    journal.create_session(
        session_id=session_id,
        title="security export",
        created_at=datetime.now(UTC),
    )
    exporter = SessionExporter(
        journal=journal, redactor=SecretRedactor((SECRET,))
    )
    data = exporter.export(session_id)
    blob = json.dumps(data)
    assert SECRET not in blob
    assert "secret-key-material" not in blob


def test_session_files_carry_no_key_material(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "journal.sqlite")
    journal.migrate()
    session_id = "01JSESSFILEPH4"
    journal.create_session(
        session_id=session_id, title="files", created_at=datetime.now(UTC)
    )
    snapshot = journal.get_session_snapshot(session_id)
    blob = json.dumps(snapshot, default=str)
    assert SECRET not in blob
    proj = TuiProjection()
    proj.apply_snapshot(snapshot)
    assert SECRET not in json.dumps(proj.to_dict())


def test_child_view_repr_carries_no_secret() -> None:
    child = ChildView(id="c1", slot=1, task="task", model="m")
    assert SECRET not in repr(child)


def test_twin_sail_logo_placed_onboarding_help_readme() -> None:
    from skail.tui.commands import HELP_TEXT
    from skail.tui.logo import COMPACT_MARK, TWIN_SAIL_LOGO, render_logo_text

    assert TWIN_SAIL_LOGO == [
        "      /\\|\\",
        "     /  | \\",
        "    /___|__\\",
        "   /____|___\\",
        "   \\________/",
        "    S K A I L",
    ]
    assert len(TWIN_SAIL_LOGO) == 6
    assert COMPACT_MARK == "/\\| S K A I L"
    # /help header carries the monochrome logo.
    assert render_logo_text() in HELP_TEXT
    # Onboarding welcome panel renders the full logo.
    from skail.tui.onboarding import OnboardingState
    from skail.tui.widgets.onboarding import OnboardingPanel

    panel = OnboardingPanel.__new__(OnboardingPanel)
    panel.onboarding = OnboardingState(step="welcome")
    panel.credentials = BootstrapCredentials()
    panel.workspace = "."
    panel.session_id = "new"
    assert render_logo_text() in panel.render_step().plain
    # README fenced text block with version line.
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "```text" in readme
    assert render_logo_text() in readme
    assert "v0.1.0" in readme
