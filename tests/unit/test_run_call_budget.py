import pytest

from skail.runtime.failure_monitor import RunModelCallBudget, RunModelCallLimitExceeded


def test_run_model_call_budget_blocks_the_first_call_past_its_limit() -> None:
    budget = RunModelCallBudget(max_calls=2)

    budget.begin_call()
    budget.begin_call()

    with pytest.raises(RunModelCallLimitExceeded, match="run.model_call_limit_exhausted"):
        budget.begin_call()

    assert budget.calls_started == 2
