from __future__ import annotations

import json

from pydantic import ValidationError

from rudder.domain.ids import TaskId
from rudder.domain.tasks import TaskResult


def parse_child_result(
    output: str,
    *,
    task_id: TaskId,
    required_criteria: tuple[str, ...],
) -> TaskResult:
    try:
        payload = json.loads(output)
        if not isinstance(payload, dict):
            raise ValueError("child result must be an object")
        payload["task_id"] = str(task_id)
        result = TaskResult.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, ValueError):
        return TaskResult(
            task_id=task_id,
            status="failed",
            summary="child returned an invalid result",
            follow_up="child must return a structured TaskResult",
        )
    return evaluate_result(result, required_criteria=required_criteria)


def evaluate_result(
    result: TaskResult,
    *,
    required_criteria: tuple[str, ...] = (),
    expected_task_id: TaskId | None = None,
) -> TaskResult:
    if expected_task_id is not None and result.task_id != expected_task_id:
        return result.model_copy(
            update={"status": "failed", "follow_up": "task result identity mismatch"}
        )

    if result.status == "succeeded":
        if not result.verification:
            return result.model_copy(
                update={
                    "status": "failed",
                    "follow_up": "evidence-bearing verification is required",
                }
            )

        # Any reported failing verification item fails the claimed success
        for item in result.verification:
            if not item.passed:
                return result.model_copy(
                    update={
                        "status": "failed",
                        "follow_up": f"verification failed for: {item.criterion}",
                    }
                )

        # Every required criterion must be present with passed=True and non-empty evidence
        verification_by_criterion = {item.criterion: item for item in result.verification}
        for criterion in required_criteria:
            matched = verification_by_criterion.get(criterion)
            if (
                matched is None
                or not matched.passed
                or not (matched.evidence and matched.evidence.strip())
            ):
                return result.model_copy(
                    update={
                        "status": "failed",
                        "follow_up": (
                            f"required verification missing or lacks evidence: {criterion}"
                        ),
                    }
                )

    return result
