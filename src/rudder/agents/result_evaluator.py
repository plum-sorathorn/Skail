from __future__ import annotations

from rudder.domain.ids import TaskId
from rudder.domain.tasks import TaskResult


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
