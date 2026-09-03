from __future__ import annotations

import json
import re
from collections import Counter, deque
from typing import Any, Literal

from rudder.domain.events import SecretRedactor

Boundary = Literal["model_calls", "time", "budget"]


class FailureMonitor:
    def __init__(self, redactor: SecretRedactor | None = None) -> None:
        self._redactor = redactor or SecretRedactor()
        self._calls: deque[str] = deque(maxlen=3)
        self._error_counts: Counter[str] = Counter()
        self._consecutive_errors = 0

    def observe_call(self, name: str, arguments: object) -> str | None:
        value = f"{name}:{_canonical(arguments, self._redactor)}"
        self._calls.append(value)
        self._consecutive_errors = 0
        if len(self._calls) == 3 and len(set(self._calls)) == 1:
            return "failure.repeated_call"
        return None

    def observe_error(self, error: object, *, blocked: bool = False) -> str | None:
        if blocked:
            self._consecutive_errors = 0
            return None
        value = _normalize_error(str(self._redactor.scrub(str(error))))
        self._consecutive_errors += 1
        self._error_counts[value] += 1
        if self._consecutive_errors >= 2:
            return "failure.consecutive_errors"
        if self._error_counts[value] >= 2:
            return "failure.repeated_error"
        return None

    def observe_success(self) -> None:
        self._consecutive_errors = 0
        self._calls.clear()

    @staticmethod
    def observe_boundary(boundary: Boundary, *, exhausted: bool) -> str | None:
        return f"failure.{boundary}_exhausted" if exhausted else None


def _canonical(value: object, redactor: SecretRedactor) -> str:
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
