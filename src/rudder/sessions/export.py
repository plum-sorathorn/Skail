from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rudder.domain.events import SecretRedactor
from rudder.sessions.journal import Journal, SessionSnapshot


class SessionExporter:
    def __init__(
        self,
        *,
        journal: Journal,
        redactor: SecretRedactor | None = None,
    ) -> None:
        self.journal = journal
        self.redactor = redactor or SecretRedactor()

    def export(
        self,
        session_id: str,
        verification_results: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        snapshot: SessionSnapshot = self.journal.get_session_snapshot(session_id)

        tasks_list = [
            {
                "task_id": t.task_id,
                "run_id": t.run_id,
                "description": t.description,
                "status": t.status.value,
                "idempotency_key": t.idempotency_key,
            }
            for t in snapshot.tasks
        ]

        attempts_list = [
            {
                "attempt_id": a.attempt_id,
                "task_id": a.task_id,
                "number": a.number,
                "status": a.status.value,
                "idempotency_key": a.idempotency_key,
            }
            for a in snapshot.attempts
        ]

        routes_list = [
            {
                "assignment_id": asg.assignment_id,
                "attempt_id": asg.attempt_id,
                "provider": asg.provider,
                "model": asg.model,
                "estimated_cost_usd": str(asg.estimated_cost_usd),
                "payload": asg.payload,
            }
            for asg in snapshot.assignments
        ]

        reservations_list = [
            {
                "reservation_id": r.reservation_id,
                "task_id": r.task_id,
                "amount_usd": str(r.amount_usd),
                "status": r.status,
                "idempotency_key": r.idempotency_key,
            }
            for r in snapshot.budget_reservations
        ]

        usage_list = [
            {
                "usage_id": u.usage_id,
                "task_id": u.task_id,
                "amount_usd": str(u.amount_usd),
                "authoritative": u.authoritative,
                "idempotency_key": u.idempotency_key,
            }
            for u in snapshot.usage_records
        ]

        approvals_list = [
            {
                "approval_id": ap.approval_id,
                "task_id": ap.task_id,
                "status": ap.status,
                "question": ap.question,
            }
            for ap in snapshot.approvals
        ]

        events_list = [ev.model_dump(mode="json") for ev in snapshot.events]

        raw_export: dict[str, Any] = {
            "schema_version": 1,
            "session_id": snapshot.session_id,
            "title": snapshot.title,
            "status": snapshot.status,
            "created_at": snapshot.created_at,
            "updated_at": snapshot.updated_at,
            "runs": [
                {
                    "run_id": r.run_id,
                    "status": r.status,
                    "budget_limit_usd": (
                        str(r.budget_limit_usd) if r.budget_limit_usd is not None else None
                    ),
                }
                for r in snapshot.runs
            ],
            "tasks": tasks_list,
            "attempts": attempts_list,
            "routes": routes_list,
            "budget_reservations": reservations_list,
            "usage": usage_list,
            "approvals": approvals_list,
            "verification": verification_results or {},
            "events": events_list,
        }

        # Scrub all secrets and return
        scrubbed = self.redactor.scrub(raw_export)
        assert isinstance(scrubbed, dict)
        return scrubbed


def export_session(
    session_id: str,
    journal: Journal,
    output_path: Path | str,
    redactor: SecretRedactor | None = None,
    verification_results: dict[str, str] | None = None,
) -> Path:
    exporter = SessionExporter(journal=journal, redactor=redactor)
    data = exporter.export(session_id, verification_results=verification_results)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
