from __future__ import annotations

import sys
from typing import TextIO

from skail.domain.events import EventEnvelope


def render_print_stdout(content: str, stream: TextIO | None = None) -> None:
    target = stream or sys.stdout
    target.write(content)
    if not content.endswith("\n"):
        target.write("\n")
    target.flush()


def render_print_stderr(content: str, stream: TextIO | None = None) -> None:
    target = stream or sys.stderr
    target.write(content)
    if not content.endswith("\n"):
        target.write("\n")
    target.flush()


def render_jsonl_event(event: EventEnvelope, stream: TextIO | None = None) -> None:
    target = stream or sys.stdout
    line = event.to_json()
    target.write(f"{line}\n")
    target.flush()
