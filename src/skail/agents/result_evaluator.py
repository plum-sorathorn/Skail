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
_TASK_RESULT_FIELDS = frozenset(
    {
        "task_id",
        "status",
        "summary",
        "artifacts",
        "kind",
        "path",
        "digest",
        "verification",
        "criterion",
        "passed",
        "evidence",
        "evidence_ref",
        "attempts",
        "attempt_id",
        "number",
        "model",
        "changed_paths",
        "follow_up",
        "verification_authority",
        "failure_category",
        "validation_path",
    }
)


def _safe_validation_path(error: ValidationError) -> str:
    errors = error.errors(include_input=False, include_context=False)
    if not errors:
        return "$"
    location = errors[0].get("loc", ())
    parts: list[str] = []
    for part in location:
        if isinstance(part, int):
            parts.append(str(part))
        elif isinstance(part, str) and part in _TASK_RESULT_FIELDS:
            parts.append(part)
        else:
            return "$"
    return "$" if not parts else f"$.{'.'.join(parts)}"


def _failed_result(
    result: TaskResult,
    *,
    follow_up: str,
    validation_path: str,
) -> TaskResult:
    return result.model_copy(
        update={
            "status": "failed",
            "follow_up": follow_up,
            "failure_category": "result_validation",
            "validation_path": validation_path,
        }
    )


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
            return TaskResult(
                task_id=task_id,
                status="failed",
                summary="child returned an invalid result",
                follow_up="child must return a structured TaskResult",
                failure_category="malformed_result",
                validation_path="$",
            )
        supplied_task_id = payload.get("task_id")
        if supplied_task_id is not None and supplied_task_id != str(task_id):
            return TaskResult(
                task_id=task_id,
                status="failed",
                summary="child returned a mismatched task identity",
                follow_up="task result identity mismatch",
                failure_category="result_validation",
                validation_path="$.task_id",
            )
        # Diagnostics belong to Skail and cannot be supplied by the model.
        payload.pop("failure_category", None)
        payload.pop("validation_path", None)
        payload["task_id"] = str(task_id)
        result = TaskResult.model_validate(payload)
    except json.JSONDecodeError:
        return TaskResult(
            task_id=task_id,
            status="failed",
            summary="child returned an invalid result",
            follow_up="child must return a structured TaskResult",
            failure_category="malformed_result",
            validation_path="$",
        )
    except ValidationError as error:
        return TaskResult(
            task_id=task_id,
            status="failed",
            summary="child returned an invalid result",
            follow_up="child must return a structured TaskResult",
            failure_category="result_validation",
            validation_path=_safe_validation_path(error),
        )
    except ValueError:
        return TaskResult(
            task_id=task_id,
            status="failed",
            summary="child returned an invalid result",
            follow_up="child must return a structured TaskResult",
            failure_category="malformed_result",
            validation_path="$",
        )

    evaluated = evaluate_result(
        result,
        required_criteria=required_criteria,
        expected_task_id=task_id,
        evidence_validator=evidence_validator,
        model_authored_analysis=model_authored_analysis,
        source_validator=source_validator,
    )
    if evaluated.failure_category is None:
        if evaluated.status == "failed":
            return evaluated.model_copy(update={"failure_category": "task_failure"})
        if evaluated.status == "budget_blocked":
            return evaluated.model_copy(update={"failure_category": "budget_blocked"})
    return evaluated


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
        return _failed_result(
            result,
            follow_up="task result identity mismatch",
            validation_path="$.task_id",
        )

    if result.status == "succeeded":
        if not result.verification:
            return _failed_result(
                result,
                follow_up="evidence-bearing verification is required",
                validation_path="$.verification",
            )

        # Any reported failing verification item fails the claimed success
        for index, item in enumerate(result.verification):
            if not item.passed:
                return _failed_result(
                    result,
                    follow_up=f"verification failed for: {item.criterion}",
                    validation_path=f"$.verification.{index}.passed",
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
                return _failed_result(
                    result,
                    follow_up=f"required verification missing or lacks evidence: {criterion}",
                    validation_path="$.verification",
                )

        if model_authored_analysis:
            if not result.summary.strip() or len(result.summary) > 8_000:
                return _failed_result(
                    result,
                    follow_up="analysis report is empty or oversized",
                    validation_path="$.summary",
                )
            references = tuple(
                match.group(0)
                for item in result.verification
                for match in _SOURCE_REF.finditer(item.evidence or "")
            )
            if not references or source_validator is None or not all(
                source_validator(reference) for reference in references
            ):
                return _failed_result(
                    result,
                    follow_up="analysis requires valid concrete source references",
                    validation_path="$.verification",
                )
            return result.model_copy(update={"verification_authority": "model-authored"})

        if evidence_validator is not None:
            for index, item in enumerate(result.verification):
                if item.evidence_ref is None or not evidence_validator(item.evidence_ref):
                    return _failed_result(
                        result,
                        follow_up=f"unsupported verification evidence: {item.criterion}",
                        validation_path=f"$.verification.{index}.evidence_ref",
                    )
            return result.model_copy(update={"verification_authority": "runtime"})

    return result
