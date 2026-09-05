from decimal import Decimal

from rudder.domain.events import SecretRedactor
from rudder.runtime.failure_monitor import FailureMonitor
from rudder.tools.assembly import _tool_result_status


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
