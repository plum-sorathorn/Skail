from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from rudder.domain.events import EventEnvelope, LifecyclePayload, SecretRedactor
from rudder.domain.ids import new_event_id, new_run_id, new_session_id
from rudder.sessions.export import SessionExporter, export_session
from rudder.sessions.journal import Journal

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def _seed_export_journal(journal: Journal, session_id: str, secret: str) -> None:
    journal.migrate()
    journal.create_session(session_id=session_id, title="Exportable Session", created_at=NOW)
    run_id = str(new_run_id())
    journal.create_run(
        run_id=run_id,
        session_id=session_id,
        status="completed",
        budget_limit_usd=Decimal("5.00"),
        created_at=NOW,
    )
    # Task 1
    journal.create_task(
        task_id="task-exp-1",
        run_id=run_id,
        description=f"Task with potential leak: api_key={secret}",
        status="succeeded",
        idempotency_key="k:exp-1",
        created_at=NOW,
    )
    journal.create_attempt(
        attempt_id="att-exp-1",
        task_id="task-exp-1",
        number=1,
        status="succeeded",
        idempotency_key="k:att-exp-1",
        created_at=NOW,
    )
    journal.create_assignment(
        assignment_id="asg-exp-1",
        attempt_id="att-exp-1",
        provider="fake",
        model="fake-smart",
        estimated_cost_usd=Decimal("0.75"),
        created_at=NOW,
        payload={
            "api_key": secret,
            "explanation": "Selected based on capability floor 0.80 and verified accuracy.",
            "route_decision": "direct_quality_floor",
        },
    )
    # Usage
    journal.record_usage(
        usage_id="use-exp-1",
        run_id=run_id,
        task_id="task-exp-1",
        amount_usd=Decimal("0.55"),
        authoritative=True,
        idempotency_key="k:use-exp-1",
        created_at=NOW,
    )
    # Event
    event = EventEnvelope(
        event_id=new_event_id(),
        session_id=session_id,
        run_id=run_id,
        sequence=1,
        type="session.completed",
        payload=LifecyclePayload(status="completed"),
    )
    journal.append_event(event=event)


def test_session_export_includes_required_sections_and_redacts_secrets(tmp_path: Path) -> None:
    secret = "sk-super-secret-token-12345"
    redactor = SecretRedactor(secrets=[secret])
    journal = Journal(tmp_path / "journal.sqlite", redactor=redactor)
    session_id = str(new_session_id())
    _seed_export_journal(journal, session_id, secret)

    exporter = SessionExporter(journal=journal, redactor=redactor)
    exported = exporter.export(
        session_id=session_id,
        verification_results={"task-exp-1": "All 5 assertions passed cleanly"},
    )

    # 1. Structure validation
    assert exported["session_id"] == session_id
    assert exported["title"] == "Exportable Session"
    assert "tasks" in exported
    assert "routes" in exported
    assert "usage" in exported
    assert "verification" in exported
    assert "events" in exported

    # Task verification
    assert len(exported["tasks"]) == 1
    task = exported["tasks"][0]
    assert task["task_id"] == "task-exp-1"
    assert task["status"] == "succeeded"

    # Route verification
    assert len(exported["routes"]) == 1
    route = exported["routes"][0]
    assert route["model"] == "fake-smart"
    assert "explanation" in route["payload"]
    assert "direct_quality_floor" in route["payload"]["route_decision"]

    # Usage verification
    assert len(exported["usage"]) == 1
    assert exported["usage"][0]["amount_usd"] == "0.55"
    assert exported["usage"][0]["authoritative"] is True

    # Verification results
    assert exported["verification"]["task-exp-1"] == "All 5 assertions passed cleanly"

    # Events verification
    assert len(exported["events"]) >= 1

    # 2. Redaction check: ensure secret NEVER appears anywhere in export
    export_json = json.dumps(exported)
    assert secret not in export_json
    assert (
        "[REDACTED]" in export_json
        or "api_key" not in export_json
        or route["payload"]["api_key"] == "[REDACTED]"
    )


def test_export_session_to_file(tmp_path: Path) -> None:
    redactor = SecretRedactor(secrets=["my-secret-pw"])
    journal = Journal(tmp_path / "journal.sqlite", redactor=redactor)
    session_id = str(new_session_id())
    _seed_export_journal(journal, session_id, "my-secret-pw")

    out_file = tmp_path / "export.json"
    export_session(
        session_id=session_id,
        journal=journal,
        output_path=out_file,
        redactor=redactor,
    )
    assert out_file.exists()
    content = json.loads(out_file.read_text(encoding="utf-8"))
    assert content["session_id"] == session_id
    assert "my-secret-pw" not in out_file.read_text(encoding="utf-8")
