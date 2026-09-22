"""Feature-gated durable workflow plans for isolated OMA executions."""
from __future__ import annotations

import fnmatch
import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TaskPlan:
    id: str
    session_id: str
    goal: str
    allowed_paths: list[str]
    acceptance_checks: list[str]
    risk: str = "normal"
    status: str = "pending"
    attempts: int = 0
    verifier: dict[str, Any] = field(default_factory=lambda: {"status": "pending"})

    @classmethod
    def new(cls, session_id: str, goal: str, allowed_paths: list[str], acceptance_checks: list[str], *, risk: str = "normal") -> "TaskPlan":
        if risk in {"high", "critical"} and not acceptance_checks:
            raise ValueError("high-risk workflow requires an acceptance check")
        return cls(uuid.uuid4().hex, session_id, goal, allowed_paths or ["**"], acceptance_checks, risk)


class WorkflowStore:
    """Atomic local persistence; callers choose when to execute a saved plan."""
    def __init__(self, root: Path) -> None:
        self.root = root

    def save(self, plan: TaskPlan) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=f"{plan.id}-", suffix=".json", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(asdict(plan), handle, separators=(",", ":"))
            os.replace(temp, self.root / f"{plan.id}.json")
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def load(self, plan_id: str) -> TaskPlan:
        value = json.loads((self.root / f"{plan_id}.json").read_text(encoding="utf-8"))
        return TaskPlan(**value)


def validate_patch_paths(paths: list[str], allowed_paths: list[str]) -> list[str]:
    """Return paths violating the plan's glob scope; never inspect file contents."""
    return [path for path in paths if not any(fnmatch.fnmatch(path.replace("\\", "/"), pattern) for pattern in allowed_paths)]


def approve_verifier(plan: TaskPlan, *, approved: bool, evidence: list[str]) -> None:
    """Apply a separately supplied verifier outcome without executing checks here."""
    plan.verifier = {"status": "approved" if approved else "rejected", "approved": approved, "evidence": evidence[:20]}
    plan.status = "verified" if approved else "needs_review"


def workflow_store() -> WorkflowStore:
    from skail.config.paths import run_dir
    return WorkflowStore(run_dir() / "workflows")
