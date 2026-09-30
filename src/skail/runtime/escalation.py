from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class FailureHandoff:
    summary: str
    evidence: tuple[str, ...]
    changed_paths: tuple[str, ...]
    verification: tuple[str, ...]
    failure_category: str | None = None
    validation_path: str | None = None


def escalation_floor(current_floor: float | None) -> float | None:
    if current_floor is None:
        return None
    return min(round(current_floor + 0.15, 2), 0.90)


def bounded_handoff(
    *, summary: str,
    evidence: tuple[str, ...] = (),
    changed_paths: tuple[str, ...] = (),
    verification: tuple[str, ...] = (),
    max_items: int = 8,
    failure_category: str | None = None,
    validation_path: str | None = None,
) -> FailureHandoff:
    if failure_category not in {
        "provider_error",
        "malformed_result",
        "result_validation",
        "routing_ineligible",
        "budget_blocked",
        "task_failure",
    }:
        failure_category = None
    if validation_path is not None and re.fullmatch(
        r"\$(?:\.[A-Za-z_][A-Za-z0-9_]*|\.[0-9]+)*", validation_path
    ) is None:
        validation_path = None
    return FailureHandoff(
        summary[:1_000],
        evidence[:max_items],
        changed_paths[:max_items],
        verification[:max_items],
        failure_category,
        validation_path,
    )
