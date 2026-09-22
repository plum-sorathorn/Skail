from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ErrorDetail:
    code: str
    summary: str
    details: dict[str, Any]
    retry_safe: bool = False


class FrameworkContractError(RuntimeError):
    """Raised when a pinned framework violates a Skail-owned invariant."""

    def __init__(self, code: str, summary: str, **details: Any) -> None:
        self.error = ErrorDetail(code=code, summary=summary, details=details)
        super().__init__(f"{code}: {summary}")
