from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from rudder.agents.context import (
    CONTEXT_PACKET_VERSION,
    ContextAssembler,
    ContextComponent,
    ContextPacket,
    _tokens,
)
from rudder.domain.events import SecretRedactor
from rudder.sessions.journal import Journal, SessionSnapshot


@dataclass(frozen=True)
class SourceCoverage:
    covered_event_ids: tuple[str, ...] = ()
    covered_events_count: int = 0
    covered_message_count: int = 0
    dropped_detail_count: int = 0


@dataclass(frozen=True)
class SessionCompactionInput:
    session_id: str
    objective: str
    constraints: tuple[str, ...] = ()
    terminal_result_summaries: dict[str, str] = field(default_factory=dict)
    changed_paths: tuple[str, ...] = ()
    verification: str = ""
    verbose_events: tuple[dict[str, Any], ...] = ()
    artifacts: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class CompactionResult:
    ok: bool
    context_packet: ContextPacket
    source_coverage: SourceCoverage
    summary_text: str


class CompactionService:
    def __init__(
        self,
        *,
        journal: Journal,
        max_context_tokens: int = 2000,
        redactor: SecretRedactor | None = None,
    ) -> None:
        self.journal = journal
        self.max_context_tokens = max_context_tokens
        self.redactor = redactor or SecretRedactor()
        self.assembler = ContextAssembler(
            max_tokens=max_context_tokens, redactor=self.redactor
        )

    def compact(self, input: SessionCompactionInput) -> CompactionResult:
        snapshot: SessionSnapshot = self.journal.get_session_snapshot(input.session_id)

        # 1. User intent and constraints
        objective_text = input.objective or "No active objective"
        constraints_text = (
            "\n".join(f"- {c}" for c in input.constraints) if input.constraints else "None"
        )

        # 2. Active tasks and terminal result summaries
        active_tasks = [t for t in snapshot.tasks if t.status.value in ("queued", "running")]
        tasks_text = (
            "\n".join(f"- {t.task_id} [{t.status.value}]: {t.description}" for t in active_tasks)
            or "None active"
        )

        results_lines: list[str] = []
        for task_id, summary in input.terminal_result_summaries.items():
            results_lines.append(f"- {task_id}: {summary}")
        # Add succeeded tasks from snapshot if not already summarized
        for t in snapshot.tasks:
            if t.status.value == "succeeded" and t.task_id not in input.terminal_result_summaries:
                results_lines.append(f"- {t.task_id} [succeeded]: {t.description}")
        results_text = "\n".join(results_lines) or "No completed tasks yet"

        # 3. Changed files and verification
        paths_text = ", ".join(input.changed_paths) if input.changed_paths else "None"
        verif_text = input.verification or "Unverified"
        changes_verification_text = f"Changed paths: {paths_text}\nVerification: {verif_text}"

        # 4. Model and budget state
        total_usage = sum((r.amount_usd for r in snapshot.usage_records), start=Decimal("0.00"))
        active_res = sum(
            (
                r.amount_usd
                for r in snapshot.budget_reservations
                if r.status in ("active", "reserved")
            ),
            start=Decimal("0.00"),
        )
        budget_text = (
            f"Authoritative spent USD: {total_usage}\nActive reservations USD: {active_res}"
        )

        # 5. Approvals and unresolved questions
        pending_approvals = [a for a in snapshot.approvals if a.status == "pending"]
        approvals_text = (
            "\n".join(
                f"- {a.approval_id} (task {a.task_id or 'lead'}): {a.question}"
                for a in pending_approvals
            )
            if pending_approvals
            else "None pending"
        )

        # 6. References for dropped verbose details/events
        covered_event_ids: list[str] = []
        ref_lines: list[str] = []
        for ev in input.verbose_events:
            ev_id = str(ev.get("event_id", ""))
            if ev_id:
                covered_event_ids.append(ev_id)
            ev_type = ev.get("type", "event")
            ref_lines.append(f"ref:event:{ev_id} [{ev_type}]")
        for art in input.artifacts:
            art_id = str(art.get("artifact_id", art.get("path", "")))
            ref_lines.append(f"ref:artifact:{art_id}")

        references_text = "\n".join(ref_lines) if ref_lines else "No referenced artifacts/events"

        components = (
            ContextComponent(
                "objective", "current", objective_text, "current user intent",
                _tokens(objective_text)
            ),
            ContextComponent(
                "constraints", "current", constraints_text, "explicit user constraints",
                _tokens(constraints_text)
            ),
            ContextComponent(
                "tasks", "current", tasks_text, "active tasks/todos",
                _tokens(tasks_text)
            ),
            ContextComponent(
                "results", "current", results_text, "terminal result summaries",
                _tokens(results_text)
            ),
            ContextComponent(
                "changes_and_verification", "current", changes_verification_text,
                "changed files and verification", _tokens(changes_verification_text)
            ),
            ContextComponent(
                "model_and_budget", "current", budget_text, "model and budget state",
                _tokens(budget_text)
            ),
            ContextComponent(
                "approvals_and_questions", "current", approvals_text,
                "approvals and unresolved questions", _tokens(approvals_text)
            ),
            ContextComponent(
                "references", "current", references_text,
                "references to retrievable dropped details", _tokens(references_text)
            ),
        )

        scrubbed = tuple(
            ContextComponent(
                c.label,
                c.revision,
                str(self.redactor.scrub(c.content)),
                c.rationale,
                _tokens(str(self.redactor.scrub(c.content))),
                c.disposition,
            )
            for c in components
        )

        total_tokens = sum(c.estimated_tokens for c in scrubbed)
        packet = ContextPacket(
            version=CONTEXT_PACKET_VERSION,
            task_id=input.session_id,
            components=scrubbed,
            estimated_tokens=total_tokens,
            omissions=(),
        )

        source_coverage = SourceCoverage(
            covered_event_ids=tuple(covered_event_ids),
            covered_events_count=len(covered_event_ids),
            covered_message_count=len(input.verbose_events),
            dropped_detail_count=len(input.verbose_events),
        )

        summary_text = (
            f"Compacted session {input.session_id}: {total_tokens} tokens estimated, "
            f"{len(covered_event_ids)} verbose events summarized into references."
        )

        return CompactionResult(
            ok=True,
            context_packet=packet,
            source_coverage=source_coverage,
            summary_text=summary_text,
        )
