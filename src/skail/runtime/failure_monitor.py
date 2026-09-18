from __future__ import annotations

import json
import re
from collections import Counter, deque
from decimal import Decimal
from typing import Any, Literal, Protocol

from skail.domain.events import SecretRedactor

Boundary = Literal["model_calls", "time", "budget"]


class FailureRedactor(Protocol):
    def scrub(self, value: Any) -> Any: ...


class FailureMonitor:
    def __init__(
        self,
        redactor: FailureRedactor | None = None,
        *,
        max_calls: int | None = None,
        max_seconds: float | None = None,
        max_budget_usd: Decimal | None = None,
    ) -> None:
        self._redactor = redactor or SecretRedactor()
        self._calls: deque[str] = deque(maxlen=3)
        self._error_counts: Counter[str] = Counter()
        self._consecutive_errors = 0
        self.max_calls = max_calls
        self.max_seconds = max_seconds
        self.max_budget_usd = max_budget_usd

    def observe_call(self, name: str, arguments: object) -> str | None:
        value = f"{name}:{_canonical(arguments, self._redactor)}"
        self._calls.append(value)
        if len(self._calls) == 3 and len(set(self._calls)) == 1:
            return "failure.repeated_call"
        return None

    def observe_error(
        self, error: object, *, blocked: bool = False, tool: str | None = None
    ) -> str | None:
        if blocked:
            self._consecutive_errors = 0
            return None
        value = _normalize_error(str(self._redactor.scrub(str(error))))
        key = f"{tool}:{value}" if tool else value
        self._consecutive_errors += 1
        self._error_counts[key] += 1
        if self._error_counts[key] >= 2:
            return "failure.repeated_error"
        if self._consecutive_errors >= 2:
            return "failure.consecutive_errors"
        return None

    def observe_success(self) -> None:
        self._consecutive_errors = 0
        self._calls.clear()

    def observe_progress(self) -> None:
        self._consecutive_errors = 0

    @staticmethod
    def observe_boundary(boundary: Boundary, *, exhausted: bool) -> str | None:
        return f"failure.{boundary}_exhausted" if exhausted else None

    def check_limits(
        self,
        *,
        calls: int,
        elapsed_seconds: float,
        spent_usd: Decimal,
    ) -> str | None:
        if self.max_calls is not None and calls >= self.max_calls:
            return "failure.model_calls_exhausted"
        if self.max_seconds is not None and elapsed_seconds >= self.max_seconds:
            return "failure.time_exhausted"
        if self.max_budget_usd is not None and spent_usd >= self.max_budget_usd:
            return "failure.budget_exhausted"
        return None


def _canonical(value: object, redactor: FailureRedactor) -> str:
    scrubbed: Any = redactor.scrub(value)
    try:
        return json.dumps(scrubbed, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return repr(scrubbed)


def _normalize_error(value: str) -> str:
    return re.sub(
        r"\b[0-9a-f]{8,}\b|\b\d+\b|0x[0-9a-f]+",
        "<unstable>",
        value.lower(),
    )
