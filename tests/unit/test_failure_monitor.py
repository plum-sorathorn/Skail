from decimal import Decimal

from skail.domain.events import SecretRedactor
from skail.runtime.failure_monitor import FailureMonitor
from skail.tools.assembly import _tool_result_status


def test_monitor_triggers_only_on_deterministic_repetition() -> None:
    monitor = FailureMonitor()
    assert monitor.observe_call("read", {"path": "a"}) is None
    assert monitor.observe_call("read", {"path": "a"}) is None
    assert monitor.observe_call("read", {"path": "a"}) == "failure.repeated_call"
    assert monitor.observe_error("permission denied", blocked=True) is None
    assert monitor.observe_error("error 123") is None
    assert monitor.observe_error("different failure") == "failure.consecutive_errors"


def test_same_normalized_error_and_boundaries_trigger_without_leaking_secrets() -> None:
    monitor = FailureMonitor(SecretRedactor(["canary-secret"]))
    assert monitor.observe_error("error 123 canary-secret") is None
    monitor.observe_success()
    assert monitor.observe_error("error 456 canary-secret") == "failure.repeated_error"
    assert monitor.observe_boundary("budget", exhausted=True) == "failure.budget_exhausted"


def test_call_arguments_are_canonical_and_corrected_progress_resets_streaks() -> None:
    monitor = FailureMonitor()
    assert monitor.observe_call("read", {"b": 2, "a": 1}) is None
    assert monitor.observe_call("read", {"a": 1, "b": 2}) is None


def test_tool_calls_do_not_erase_consecutive_error_state() -> None:
    monitor = FailureMonitor()
    assert monitor.observe_error("first failure") is None
    assert monitor.observe_call("read", {"path": "a"}) is None
    assert monitor.observe_error("second failure") == "failure.consecutive_errors"


def test_successful_progress_resets_consecutive_error_state() -> None:
    monitor = FailureMonitor()
    assert monitor.observe_error("first failure") is None
    monitor.observe_progress()
    assert monitor.observe_error("second failure") is None


def test_repeated_normalized_error_wins_over_generic_consecutive_signal() -> None:
    monitor = FailureMonitor()
    assert monitor.observe_error("request 123 failed") is None
    assert monitor.observe_error("request 456 failed") == "failure.repeated_error"


def test_execution_status_dictionaries_classify_failure_and_blocking() -> None:
    assert _tool_result_status({"status": "failed"}) == "error"
    assert _tool_result_status({"status": "rejected"}) == "blocked"
    assert _tool_result_status({"status": "approval_required"}) == "blocked"
    assert _tool_result_status({"status": "completed", "returncode": 0}) == "success"


def test_configured_call_time_and_budget_limits_fail_deterministically() -> None:
    monitor = FailureMonitor(
        max_calls=4,
        max_seconds=30.0,
        max_budget_usd=Decimal("1.00"),
    )

    assert monitor.check_limits(calls=3, elapsed_seconds=29.0, spent_usd=Decimal("0.99")) is None
    assert monitor.check_limits(calls=4, elapsed_seconds=0, spent_usd=Decimal("0")) == (
        "failure.model_calls_exhausted"
    )
    assert monitor.check_limits(calls=0, elapsed_seconds=30.0, spent_usd=Decimal("0")) == (
        "failure.time_exhausted"
    )
    assert monitor.check_limits(calls=0, elapsed_seconds=0, spent_usd=Decimal("1.00")) == (
        "failure.budget_exhausted"
    )
    monitor.observe_success()
    assert monitor.observe_call("read", {"a": 1, "b": 2}) is None


def test_never_executed_calls_are_exempt_from_the_repeated_call_window() -> None:
    orphan = FailureMonitor()
    assert orphan.observe_call("read", {"path": "a"}, executed=False) is None
    assert orphan.observe_call("read", {"path": "a"}, executed=False) is None
    assert orphan.observe_call("read", {"path": "a"}, executed=False) is None

    executed = FailureMonitor()
    assert executed.observe_call("read", {"path": "a"}, executed=True) is None
    assert executed.observe_call("read", {"path": "a"}, executed=True) is None
    assert executed.observe_call("read", {"path": "a"}, executed=True) == "failure.repeated_call"


def test_interleaved_orphans_do_not_count_toward_the_call_window() -> None:
    monitor = FailureMonitor()
    assert monitor.observe_call("read", {"path": "a"}, executed=False) is None
    assert monitor.observe_call("read", {"path": "a"}) is None
    assert monitor.observe_call("read", {"path": "a"}, executed=False) is None
    assert monitor.observe_call("read", {"path": "a"}) is None
    assert monitor.observe_call("read", {"path": "a"}, executed=False) is None
    # Only the two executed calls ever entered the window; the third executed
    # call completes it and trips.
    assert monitor.observe_call("read", {"path": "a"}) == "failure.repeated_call"
    # observe_success still clears the window.
    monitor.observe_success()
    assert monitor.observe_call("read", {"path": "a"}) is None
    assert monitor.observe_call("read", {"path": "a"}) is None
    assert monitor.observe_call("read", {"path": "a"}) == "failure.repeated_call"


def test_orphan_surfaces_as_tool_scoped_repeated_error_without_call_window() -> None:
    monitor = FailureMonitor()
    # Orphan #1: the call never reached a handler; the defect is counted
    # tool-scoped and the call contributes nothing to the repeated-call window.
    assert monitor.observe_call("task", {"description": "x"}, executed=False) is None
    assert monitor.observe_error("validation failed: args", tool="task") is None
    # Orphan #2: the tool-scoped repeated_error trips at the second occurrence.
    assert monitor.observe_call("task", {"description": "x"}, executed=False) is None
    assert monitor.observe_error("validation failed: args", tool="task") == (
        "failure.repeated_error"
    )
    # Regression: a third identical call that finally executes trips nothing
    # (no failure.repeated_call), so the run is not aborted.
    assert monitor.observe_call("task", {"description": "x"}) is None
    assert monitor.observe_call("task", {"description": "x"}) is None
    assert monitor.observe_call("task", {"description": "x"}) == "failure.repeated_call"
