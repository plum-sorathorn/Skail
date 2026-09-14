from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FailureHandoff:
    summary: str
    evidence: tuple[str, ...]
    changed_paths: tuple[str, ...]
    verification: tuple[str, ...]


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
) -> FailureHandoff:
    return FailureHandoff(
        summary[:1_000], evidence[:max_items], changed_paths[:max_items], verification[:max_items]
    )
