from rudder.domain.events import SecretRedactor
from rudder.runtime.failure_monitor import FailureMonitor


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
    monitor.observe_success()
    assert monitor.observe_call("read", {"a": 1, "b": 2}) is None
