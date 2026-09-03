from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rudder.runtime.redaction import RedactionRegistry


@dataclass(frozen=True)
class CapturedOutput:
    excerpt: str
    truncated: bool
    artifact_path: Path | None


class ArtifactStore:
    def __init__(
        self, root: Path, redactor: RedactionRegistry, *, excerpt_chars: int = 8_000
    ) -> None:
        self.root = root
        self.redactor = redactor
        self.excerpt_chars = excerpt_chars

    def capture(self, tool: str, value: Any) -> CapturedOutput:
        text = self.redactor.scrub_text(value if isinstance(value, str) else repr(value))
        if len(text) <= self.excerpt_chars:
            return CapturedOutput(text, False, None)
        self.root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(text.encode()).hexdigest()
        path = self.root / f"{tool}-{digest}.txt"
        path.write_text(text, encoding="utf-8")
        excerpt = text[: self.excerpt_chars] + f"\n[truncated; artifact={path.name}]"
        return CapturedOutput(excerpt, True, path)
