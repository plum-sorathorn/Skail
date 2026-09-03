from __future__ import annotations

import logging
import traceback
from threading import RLock
from typing import Any

from rudder.domain.events import SecretRedactor


class RedactionRegistry:
    def __init__(self) -> None:
        self._values: set[str] = set()
        self._lock = RLock()

    def register(self, value: str) -> None:
        if not value:
            return
        with self._lock:
            self._values.add(value)

    def redactor(self) -> SecretRedactor:
        with self._lock:
            return SecretRedactor(tuple(self._values))

    def scrub(self, value: Any) -> Any:
        return self.redactor().scrub(value)

    def scrub_text(self, value: str) -> str:
        scrubbed = self.scrub(value)
        assert isinstance(scrubbed, str)
        return scrubbed

    def scrub_exception(self, error: BaseException) -> tuple[str, ...]:
        messages: list[str] = []
        current: BaseException | None = error
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            messages.append(self.scrub_text(str(current)))
            current = current.__cause__ or current.__context__
        return tuple(messages)

    def scrub_tool_output(self, value: Any) -> Any:
        return self.scrub(value)

    def scrub_export(self, value: Any) -> Any:
        return self.scrub(value)


class RedactingLogFilter(logging.Filter):
    def __init__(self, registry: RedactionRegistry) -> None:
        super().__init__()
        self.registry = registry

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self.registry.scrub_text(record.getMessage())
        record.args = ()
        if record.exc_info is not None:
            rendered = "".join(traceback.format_exception(*record.exc_info))
            record.exc_text = self.registry.scrub_text(rendered)
            record.exc_info = None
        return True
