from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from skail.domain.events import SecretRedactor
from skail.sessions.journal import Journal, SessionSnapshot


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
                "authority": u.authority,
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

        with self.journal._connect() as connection:
            call_rows = connection.execute(
                "SELECT c.call_id,c.status,c.input_tokens,c.output_tokens,c.amount_usd,"
                "c.authority,u.cached_input_tokens,a.assignment_id,a.provider,a.model,"
                "a.payload_json,t.task_id,t.run_id "
                "FROM provider_calls c "
                "JOIN assignments a ON a.assignment_id=c.assignment_id "
                "JOIN attempts p ON p.attempt_id=a.attempt_id "
                "JOIN tasks t ON t.task_id=p.task_id "
                "JOIN runs r ON r.run_id=t.run_id "
                "LEFT JOIN assignment_call_usage u "
                "ON u.assignment_id=a.assignment_id AND u.call_id=c.call_id "
                "WHERE r.session_id=? ORDER BY c.created_at,c.call_id",
                (session_id,),
            ).fetchall()
        provider_calls = []
        model_totals: dict[tuple[str, str], dict[str, Any]] = {}
        for row in call_rows:
            pricing = json.loads(row["payload_json"]).get("pricing_evidence", {})
            provider_calls.append(
                {
                    "call_id": row["call_id"],
                    "run_id": row["run_id"],
                    "task_id": row["task_id"],
                    "assignment_id": row["assignment_id"],
                    "provider": row["provider"],
                    "model": row["model"],
                    "status": row["status"],
                    "input_tokens": row["input_tokens"],
                    "output_tokens": row["output_tokens"],
                    "cached_input_tokens": row["cached_input_tokens"],
                    "cost_usd": row["amount_usd"],
                    "authority": row["authority"],
                    "pricing_evidence": pricing,
                }
            )
            key = (row["provider"], row["model"])
            total = model_totals.setdefault(
                key,
                {
                    "provider": key[0],
                    "model": key[1],
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cached_input_tokens": 0,
                    "known_cost_usd": Decimal("0"),
                    "unresolved_calls": 0,
                },
            )
            total["input_tokens"] += row["input_tokens"] or 0
            total["output_tokens"] += row["output_tokens"] or 0
            total["cached_input_tokens"] += row["cached_input_tokens"] or 0
            if (
                row["amount_usd"] is None
                or row["input_tokens"] is None
                or row["output_tokens"] is None
            ):
                total["unresolved_calls"] += 1
            else:
                total["known_cost_usd"] += Decimal(row["amount_usd"])
        model_usage = [
            {
                **{k: v for k, v in total.items() if k != "known_cost_usd"},
                "known_cost_usd": format(total["known_cost_usd"], "f"),
                "total_cost_usd": (
                    None
                    if total["unresolved_calls"]
                    else format(total["known_cost_usd"], "f")
                ),
            }
            for _, total in sorted(model_totals.items())
        ]

        raw_export: dict[str, Any] = {
            "schema_version": 2,
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
            "provider_calls": provider_calls,
            "model_usage": model_usage,
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
