from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from skail.domain.security import ProjectTrustLevel
from skail.runtime.redaction import RedactionRegistry


@dataclass(frozen=True)
class ContextSource:
    label: str
    revision: str
    content: str
    truncated: bool


def load_context(
    path: Path, *, label: str, trust: ProjectTrustLevel, project_owned: bool, limit: int = 8_000
) -> ContextSource | None:
    if project_owned and trust is not ProjectTrustLevel.TRUSTED:
        return None
    raw = path.read_text(encoding="utf-8")
    return ContextSource(
        label, hashlib.sha256(raw.encode()).hexdigest(), raw[:limit], len(raw) > limit
    )


def load_bounded_contexts(
    paths: tuple[Path, ...],
    *,
    root: Path,
    label: str,
    trust: ProjectTrustLevel,
    project_owned: bool,
    redactor: RedactionRegistry,
    total_limit: int = 16_000,
) -> tuple[ContextSource, ...]:
    remaining = total_limit
    loaded: list[ContextSource] = []
    canonical_root = root.resolve(strict=True)
    for path in paths:
        canonical = path.resolve(strict=True)
        try:
            canonical.relative_to(canonical_root)
        except ValueError as error:
            raise PermissionError("context source escapes its configured root") from error
        item = load_context(
            canonical,
            label=f"{label}:{canonical.name}",
            trust=trust,
            project_owned=project_owned,
            limit=remaining,
        )
        if item is None:
            continue
        scrubbed = redactor.scrub_text(item.content)
        content = scrubbed[:remaining]
        loaded.append(
            ContextSource(
                item.label,
                item.revision,
                content,
                item.truncated or len(scrubbed) > remaining,
            )
        )
        remaining -= len(content)
        if remaining <= 0:
            break
    return tuple(loaded)
