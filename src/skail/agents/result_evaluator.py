from __future__ import annotations

import json
import re
from collections.abc import Callable

from pydantic import ValidationError

from skail.domain.ids import TaskId
from skail.domain.tasks import ArtifactRef, TaskResult

EvidenceValidator = Callable[[ArtifactRef], bool]
SourceValidator = Callable[[str], bool]
_SOURCE_REF = re.compile(r"(?P<path>[A-Za-z0-9_.\\/-]+):(?P<line>[1-9][0-9]*)")


def parse_child_result(
    output: str,
    *,
    task_id: TaskId,
    required_criteria: tuple[str, ...],
    evidence_validator: EvidenceValidator | None = None,
    model_authored_analysis: bool = False,
    source_validator: SourceValidator | None = None,
) -> TaskResult:
    try:
        payload = json.loads(output)
        if not isinstance(payload, dict):
            raise ValueError("child result must be an object")
        supplied_task_id = payload.get("task_id")
        if supplied_task_id is not None and supplied_task_id != str(task_id):
            return TaskResult(
                task_id=task_id,
                status="failed",
                summary="child returned a mismatched task identity",
                follow_up="task result identity mismatch",
            )
        payload["task_id"] = str(task_id)
        result = TaskResult.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, ValueError):
        return TaskResult(
            task_id=task_id,
            status="failed",
            summary="child returned an invalid result",
            follow_up="child must return a structured TaskResult",
        )
    return evaluate_result(
        result,
        required_criteria=required_criteria,
        expected_task_id=task_id,
        evidence_validator=evidence_validator,
        model_authored_analysis=model_authored_analysis,
        source_validator=source_validator,
    )


def evaluate_result(
    result: TaskResult,
    *,
    required_criteria: tuple[str, ...] = (),
    expected_task_id: TaskId | None = None,
    evidence_validator: EvidenceValidator | None = None,
    model_authored_analysis: bool = False,
    source_validator: SourceValidator | None = None,
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

        if model_authored_analysis:
            if not result.summary.strip() or len(result.summary) > 8_000:
                return result.model_copy(
                    update={
                        "status": "failed",
                        "follow_up": "analysis report is empty or oversized",
                    }
                )
            references = tuple(
                match.group(0)
                for item in result.verification
                for match in _SOURCE_REF.finditer(item.evidence or "")
            )
            if not references or source_validator is None or not all(
                source_validator(reference) for reference in references
            ):
                return result.model_copy(
                    update={
                        "status": "failed",
                        "follow_up": "analysis requires valid concrete source references",
                    }
                )
            return result.model_copy(update={"verification_authority": "model-authored"})

        if evidence_validator is not None:
            for item in result.verification:
                if item.evidence_ref is None or not evidence_validator(item.evidence_ref):
                    return result.model_copy(
                        update={
                            "status": "failed",
                            "follow_up": f"unsupported verification evidence: {item.criterion}",
                        }
                    )
            return result.model_copy(update={"verification_authority": "runtime"})

    return result
