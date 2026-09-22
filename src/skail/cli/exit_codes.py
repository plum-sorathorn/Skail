from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    OK = 0
    FAILURE = 1
    USAGE = 2
    BLOCKED = 3
    CANCELLED = 4


EXIT_OK = ExitCode.OK.value
EXIT_FAILURE = ExitCode.FAILURE.value
EXIT_USAGE = ExitCode.USAGE.value
EXIT_BLOCKED = ExitCode.BLOCKED.value
EXIT_CANCELLED = ExitCode.CANCELLED.value
