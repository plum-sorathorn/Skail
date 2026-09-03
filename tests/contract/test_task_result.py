from rudder.agents.result_evaluator import evaluate_result
from rudder.domain.ids import new_task_id
from rudder.domain.tasks import TaskResult, VerificationResult


def test_success_requires_every_required_verification() -> None:
    result = TaskResult(
        task_id=new_task_id(),
        status="succeeded",
        summary="claimed success",
        verification=(VerificationResult(criterion="tests", passed=False),),
    )
    evaluated = evaluate_result(result, required_criteria=("tests",))
    assert evaluated.status == "failed"


def test_success_requires_non_empty_evidence() -> None:
    task_id = new_task_id()
    result_no_evidence = TaskResult(
        task_id=task_id,
        status="succeeded",
        summary="claimed success",
        verification=(VerificationResult(criterion="tests", passed=True, evidence="  "),),
    )
    evaluated_no_evidence = evaluate_result(result_no_evidence, required_criteria=("tests",))
    assert evaluated_no_evidence.status == "failed"

    result_with_evidence = TaskResult(
        task_id=task_id,
        status="succeeded",
        summary="claimed success",
        verification=(VerificationResult(criterion="tests", passed=True, evidence="3 passed"),),
    )
    evaluated_with_evidence = evaluate_result(result_with_evidence, required_criteria=("tests",))
    assert evaluated_with_evidence.status == "succeeded"


def test_empty_required_criteria_succeeds_deterministically() -> None:
    task_id = new_task_id()
    result = TaskResult(task_id=task_id, status="succeeded", summary="done")
    evaluated = evaluate_result(result, required_criteria=())
    assert evaluated.status == "succeeded"

    # But any failing reported verification still causes failure
    result_with_failure = TaskResult(
        task_id=task_id,
        status="succeeded",
        summary="done",
        verification=(VerificationResult(criterion="lint", passed=False),),
    )
    assert evaluate_result(result_with_failure, required_criteria=()).status == "failed"


def test_task_identity_mismatch_fails_safely() -> None:
    result = TaskResult(task_id=new_task_id(), status="succeeded", summary="done")
    evaluated = evaluate_result(result, expected_task_id=new_task_id())
    assert evaluated.status == "failed"
    assert evaluated.follow_up == "task result identity mismatch"

