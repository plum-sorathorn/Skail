from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path

import pytest

from skail.cli.main import _build_storage
from skail.domain.ids import SessionId, new_session_id
from skail.providers.credentials import EnvironmentCredentialResolver
from skail.providers.fake import DeterministicFakeChatModel
from skail.runtime.redaction import RedactingLogFilter, RedactionRegistry
from skail.runtime.run_controller import RunController
from skail.sessions.checkpoints import CheckpointStore
from skail.sessions.export import export_session
from skail.sessions.journal import Journal
from skail.sessions.service import SessionService


def test_cli_storage_uses_the_run_scoped_redaction_registry(tmp_path: Path) -> None:
    redaction = RedactionRegistry()
    journal, checkpoints, sessions = _build_storage(
        no_session=True,
        redaction=redaction,
        ephemeral_dir=tmp_path,
    )

    assert journal.redactor is redaction
    assert checkpoints.redactor is redaction
    assert sessions == tmp_path / "sessions"


@pytest.mark.asyncio
async def test_resolved_credential_never_leaks_to_persisted_or_displayed_surfaces(
    tmp_path: Path,
) -> None:
    canary = "sk-live-canary-secret-9999988888"
    redaction = RedactionRegistry()

    # 1. Resolve credential into shared redaction registry
    resolver = EnvironmentCredentialResolver(
        redaction, environment={"CANARY_API_KEY": canary}
    )
    resolved = resolver.resolve("test-provider", "CANARY_API_KEY")
    assert resolved.reveal() == canary
    assert canary not in repr(resolved)
    assert "[REDACTED]" in repr(resolved)

    # 2. Wire single redaction registry into Journal, Checkpoints, and Controller
    journal_path = tmp_path / "journal.sqlite"
    checkpoints_path = tmp_path / "checkpoints.sqlite"
    export_path = tmp_path / "export.json"

    journal = Journal(journal_path, redactor=redaction)
    checkpoints = CheckpointStore(checkpoints_path, redactor=redaction)
    journal.migrate()
    checkpoints.initialize()

    session_id = str(new_session_id())
    session_service = SessionService(
        journal=journal,
        checkpoints=checkpoints,
        sessions_dir=tmp_path / "sessions",
    )
    session_service.create_session(session_id=session_id, title="Canary Session")

    # 3. Setup logging with RedactingLogFilter
    logger = logging.getLogger("skail.canary.test")
    log_filter = RedactingLogFilter(redaction)
    logger.addFilter(log_filter)
    log_records: list[str] = []

    class CapturingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            log_records.append(record.getMessage())

    handler = CapturingHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    logger.info("Starting run with sensitive info: %s", canary)
    assert canary not in log_records[0]
    assert "[REDACTED]" in log_records[0]

    # 4. Run instruction containing the secret
    fake_model = DeterministicFakeChatModel(
        model_name="canary-model",
        response_text=f"Processed secret: {canary} and done.",
    )
    models = {
        "canary-model": fake_model,
        "lead-model": fake_model,
        "implementer-model": fake_model,
    }

    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    controller = RunController(
        session_id=SessionId(session_id),
        workspace=workspace_dir,
        journal=journal,
        models=models,
        default_lead_model="canary-model",
        default_child_model="canary-model",
        redaction=redaction,
        checkpoints=checkpoints,
        budget_limit_usd=Decimal("5.00"),
    )

    result = await controller.run_instruction(
        f"Do something confidential with {canary}"
    )
    assert result.run_id is not None

    # 5. Verify exception scrubbing
    try:
        raise ValueError(f"Crash containing secret: {canary}")
    except ValueError as exc:
        scrubbed_trace = redaction.scrub_exception(exc)
        for msg in scrubbed_trace:
            assert canary not in msg
            assert "[REDACTED]" in msg

    # 6. Verify export scrubbing
    export_session(session_id, journal, export_path, redactor=redaction)
    export_text = export_path.read_text(encoding="utf-8")
    assert canary not in export_text

    # 7. Verify raw SQLite file contents for Journal
    raw_journal_bytes = journal_path.read_bytes()
    assert canary.encode("utf-8") not in raw_journal_bytes

    # 8. Verify raw SQLite file contents for Checkpoints
    raw_checkpoints_bytes = checkpoints_path.read_bytes()
    assert canary.encode("utf-8") not in raw_checkpoints_bytes

    # 9. Verify session resume succeeds after terminal checkpoint
    resume_result = session_service.resume_session(session_id)
    assert resume_result.ok is True
    assert resume_result.recovery_error is None
