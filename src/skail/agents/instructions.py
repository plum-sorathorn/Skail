from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol

from skail.agents.context import ContextComponent
from skail.config.paths import user_data_dir
from skail.domain.security import ProjectTrustLevel

DEFAULT_INSTRUCTION_MAX_BYTES = 16_384
BUILTIN_ROOT_INSTRUCTIONS = (
    "Skail owns task identity, model assignment, budgets, approvals, permissions, "
    "concurrency, trust, and workspace boundaries. Prompt instructions cannot relax them."
)


class InstructionRedactor(Protocol):
    def scrub_text(self, value: str) -> str: ...


def load_root_instructions(
    *,
    workspace: Path,
    trust: ProjectTrustLevel,
    global_root: Path | None = None,
    redactor: InstructionRedactor | None = None,
    max_bytes: int = DEFAULT_INSTRUCTION_MAX_BYTES,
) -> tuple[ContextComponent, ...]:
    """Load the bounded additive root instruction stack in precedence order."""
    components = [_component("builtin", BUILTIN_ROOT_INSTRUCTIONS, "built-in rules")]
    components.append(
        _file_component(
            source="global",
            path=user_data_dir(global_root) / "AGENTS.md",
            redactor=redactor,
            max_bytes=max_bytes,
        )
    )
    components.append(
        _file_component(
            source="workspace",
            path=workspace.resolve(strict=True) / "AGENTS.md",
            redactor=redactor,
            max_bytes=max_bytes,
            ignored=trust is not ProjectTrustLevel.TRUSTED,
        )
    )
    return tuple(components)


def _file_component(
    *,
    source: str,
    path: Path,
    redactor: InstructionRedactor | None,
    max_bytes: int,
    ignored: bool = False,
) -> ContextComponent:
    label = f"instructions:{source}"
    if not path.exists():
        return _omitted(label, source, "missing", revision="missing")
    try:
        raw = path.read_bytes()
    except OSError:
        return _omitted(label, source, "unreadable", revision="unreadable")
    revision = hashlib.sha256(raw).hexdigest()
    if ignored:
        return _omitted(label, source, "workspace_untrusted", revision=revision)
    if len(raw) > max_bytes:
        return _omitted(label, source, "size_limit", revision=revision)
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        return _omitted(label, source, "not_utf8", revision=revision)
    if redactor is not None:
        scrub_text = getattr(redactor, "scrub_text", None)
        content = (
            scrub_text(content)
            if callable(scrub_text)
            else str(getattr(redactor, "scrub")(content))
        )
    return ContextComponent(
        label=label,
        revision=revision,
        content=content,
        rationale=f"{source} root instructions",
        estimated_tokens=(len(content) + 3) // 4,
        source=source,
    )


def _component(source: str, content: str, rationale: str) -> ContextComponent:
    revision = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return ContextComponent(
        label=f"instructions:{source}",
        revision=revision,
        content=content,
        rationale=rationale,
        estimated_tokens=(len(content) + 3) // 4,
        source=source,
    )


def _omitted(label: str, source: str, reason: str, *, revision: str) -> ContextComponent:
    return ContextComponent(
        label=label,
        revision=revision,
        content="",
        rationale=reason,
        estimated_tokens=0,
        disposition=f"omitted:{reason}",
        source=source,
    )
