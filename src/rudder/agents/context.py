from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Protocol

from rudder.domain.events import SecretRedactor

CONTEXT_PACKET_VERSION = 1


class ContextRedactor(Protocol):
    def scrub(self, value: Any) -> Any: ...


@dataclass(frozen=True)
class ContextComponent:
    label: str
    revision: str
    content: str
    rationale: str
    estimated_tokens: int
    disposition: str = "selected"


@dataclass(frozen=True)
class ContextPacket:
    version: int
    task_id: str
    components: tuple[ContextComponent, ...]
    estimated_tokens: int
    omissions: tuple[str, ...]

    @property
    def revision(self) -> str:
        payload = json.dumps(
            {
                "version": self.version,
                "task_id": self.task_id,
                "components": [item.__dict__ for item in self.components],
                "omissions": self.omissions,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(payload.encode("utf-8")).hexdigest()


class ContextAssembler:
    def __init__(
        self,
        *,
        max_tokens: int = 2_000,
        redactor: ContextRedactor | None = None,
    ) -> None:
        self.max_tokens = max_tokens
        self.redactor = redactor or SecretRedactor()

    def assemble(
        self,
        *,
        task_id: str,
        objective: str,
        constraints: tuple[str, ...] = (),
        state: str = "",
        references: tuple[ContextComponent, ...] = (),
    ) -> ContextPacket:
        constraint_text = "\n".join(constraints)
        required = (
            ContextComponent(
                "objective", "current", objective, "current work", _tokens(objective)
            ),
            ContextComponent(
                "constraints",
                "current",
                constraint_text,
                "explicit user constraints",
                _tokens(constraint_text),
            ),
            ContextComponent(
                "task-state", "current", state, "required persisted state", _tokens(state)
            ),
        )
        selected = [self._scrub(item) for item in required]
        omissions: list[str] = []
        for raw_component in references:
            component = self._scrub(raw_component)
            used = sum(item.estimated_tokens for item in selected)
            if used + component.estimated_tokens <= self.max_tokens:
                selected.append(component)
            else:
                omissions.append(f"{component.label}:token_budget")
        return ContextPacket(
            CONTEXT_PACKET_VERSION,
            task_id,
            tuple(selected),
            sum(item.estimated_tokens for item in selected),
            tuple(omissions),
        )

    def _scrub(self, component: ContextComponent) -> ContextComponent:
        content = str(self.redactor.scrub(component.content))
        return ContextComponent(
            component.label,
            component.revision,
            content,
            component.rationale,
            _tokens(content),
            component.disposition,
        )


def _tokens(value: str) -> int:
    return (len(value) + 3) // 4
