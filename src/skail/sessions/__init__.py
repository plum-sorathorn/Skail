from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from skail.sessions.checkpoints import CheckpointRecord, CheckpointStore
    from skail.sessions.compaction import (
        CompactionResult,
        CompactionService,
        SessionCompactionInput,
        SourceCoverage,
    )
    from skail.sessions.export import SessionExporter, export_session
    from skail.sessions.journal import (
        Journal,
        JournalBusyError,
        JournalIdempotencyError,
        PersistedChangeSet,
        SessionSnapshot,
        SessionSummary,
    )
    from skail.sessions.recovery import RecoveryResult, recover_session
    from skail.sessions.service import (
        SessionLockedError,
        SessionResumeResult,
        SessionService,
    )

__all__ = [
    "CheckpointRecord",
    "CheckpointStore",
    "CompactionResult",
    "CompactionService",
    "Journal",
    "JournalBusyError",
    "JournalIdempotencyError",
    "PersistedChangeSet",
    "RecoveryResult",
    "SessionCompactionInput",
    "SessionExporter",
    "SessionLockedError",
    "SessionResumeResult",
    "SessionService",
    "SessionSnapshot",
    "SessionSummary",
    "SourceCoverage",
    "export_session",
    "recover_session",
]

# Submodule providing each exported name. Imports stay lazy so that the
# --help/--version path never pays for the langgraph/langsmith chain.
_EXPORTS: dict[str, str] = {
    "CheckpointRecord": "skail.sessions.checkpoints",
    "CheckpointStore": "skail.sessions.checkpoints",
    "CompactionResult": "skail.sessions.compaction",
    "CompactionService": "skail.sessions.compaction",
    "SessionCompactionInput": "skail.sessions.compaction",
    "SourceCoverage": "skail.sessions.compaction",
    "SessionExporter": "skail.sessions.export",
    "export_session": "skail.sessions.export",
    "Journal": "skail.sessions.journal",
    "JournalBusyError": "skail.sessions.journal",
    "JournalIdempotencyError": "skail.sessions.journal",
    "PersistedChangeSet": "skail.sessions.journal",
    "SessionSnapshot": "skail.sessions.journal",
    "SessionSummary": "skail.sessions.journal",
    "RecoveryResult": "skail.sessions.recovery",
    "recover_session": "skail.sessions.recovery",
    "SessionLockedError": "skail.sessions.service",
    "SessionResumeResult": "skail.sessions.service",
    "SessionService": "skail.sessions.service",
}


def __getattr__(name: str) -> Any:
    if name in _EXPORTS:
        value = getattr(import_module(_EXPORTS[name]), name)
    else:  # Submodule attribute access, e.g. skail.sessions.migrations.
        try:
            value = import_module(f"skail.sessions.{name}")
        except ImportError as exc:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    globals()[name] = value  # Cache so later lookups skip this hook.
    return value
