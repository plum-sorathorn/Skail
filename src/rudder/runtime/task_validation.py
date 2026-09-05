from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path, PurePosixPath, PureWindowsPath

from rudder.agents.profile_loader import AgentProfile
from rudder.domain.ids import RunId, TaskId, ensure_uuid4, new_task_id
from rudder.domain.tasks import ModelConstraint, PermissionSet, TaskRequest, TaskSpec
from rudder.routing.requirements import ROLE_FLOORS, RequirementBuilder, TaskRisk


class TaskValidationError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class TaskValidator:
    def __init__(
        self,
        *,
        profiles: dict[str, AgentProfile],
        workspace_root: Path,
        max_depth: int,
        background_enabled: bool,
        max_description_chars: int = 20_000,
    ) -> None:
        self._profiles = profiles
        self._workspace_root = workspace_root.resolve(strict=False)
        self._max_depth = max_depth
        self._background_enabled = background_enabled
        self._max_description_chars = max_description_chars
        self._requirements = RequirementBuilder()

    def create_spec(
        self,
        request: TaskRequest,
        *,
        run_id: RunId,
        parent_task_id: TaskId | None,
        parent_depth: int,
        workspace_revision: str,
        risk: TaskRisk = TaskRisk.ROUTINE,
        budget_usd: Decimal | None = None,
        model_policy: ModelConstraint | None = None,
    ) -> TaskSpec:
        normalized = self.normalize(request, parent_depth=parent_depth)
        if not workspace_revision.strip():
            raise TaskValidationError("task.workspace_revision_invalid")
        if parent_task_id is not None:
            self._validate_id(str(parent_task_id), "task.parent_invalid")
        profile = self._profiles[normalized.profile]
        try:
            requirements = self._requirements.build(
                role=profile.role,
                risk=risk,
                role_hard_min=profile.role_floor,
                required_tools=bool(profile.tools),
                required_structured_output=profile.response_schema is not None,
            )
        except ValueError as error:
            raise TaskValidationError("task.profile_invalid") from error
        normalized = normalized.model_copy(
            update={
                "budget_usd": (
                    normalized.budget_usd if budget_usd is None else budget_usd
                ),
                "model_policy": (
                    normalized.model_policy if model_policy is None else model_policy
                ),
            }
        )
        return TaskSpec(
            task_id=new_task_id(),
            run_id=run_id,
            parent_task_id=parent_task_id,
            depth=parent_depth + 1,
            fingerprint=task_fingerprint(
                normalized,
                parent_task_id=parent_task_id,
                workspace_revision=workspace_revision,
            ),
            request=normalized,
            requirements=requirements,
            permission_set=PermissionSet(
                read=profile.permissions.read,
                write=profile.permissions.write,
                execute=profile.permissions.execute,
                network=profile.permissions.network,
                allowed_paths=normalized.write_scope,
            ),
        )

    def normalize(self, request: TaskRequest, *, parent_depth: int) -> TaskRequest:
        description = _normalize_text(request.description)
        if not description:
            raise TaskValidationError("task.description_empty")
        if len(description) > self._max_description_chars:
            raise TaskValidationError("task.description_oversized")
        profile_name = request.profile.strip()
        profile = self._profiles.get(profile_name)
        if profile is None:
            raise TaskValidationError("task.profile_unknown")
        if profile.role not in ROLE_FLOORS:
            raise TaskValidationError("task.profile_invalid")
        if parent_depth >= self._max_depth:
            raise TaskValidationError("task.depth_exceeded")
        dependencies = tuple(str(value) for value in request.depends_on)
        if len(set(dependencies)) != len(dependencies):
            raise TaskValidationError("task.dependency_invalid")
        for dependency in dependencies:
            self._validate_id(dependency, "task.dependency_invalid")
        scope = tuple(self._normalize_scope(value) for value in request.write_scope)
        if scope and not profile.permissions.write:
            raise TaskValidationError("task.scope_forbidden")
        if request.background and not self._background_enabled:
            raise TaskValidationError("task.background_disabled")
        return request.model_copy(
            update={
                "description": description,
                "profile": profile_name,
                "success_criteria": tuple(
                    _normalize_text(value) for value in request.success_criteria
                ),
                "depends_on": dependencies,
                "write_scope": scope,
            }
        )

    def _normalize_scope(self, value: str) -> str:
        candidate = value.strip().replace("\\", "/")
        windows_path = PureWindowsPath(candidate)
        posix_path = PurePosixPath(candidate)
        if (
            not candidate
            or windows_path.is_absolute()
            or windows_path.drive
            or posix_path.is_absolute()
            or ".." in posix_path.parts
        ):
            raise TaskValidationError("task.scope_invalid")
        resolved = (self._workspace_root / Path(*posix_path.parts)).resolve(strict=False)
        try:
            resolved.relative_to(self._workspace_root)
        except ValueError as error:
            raise TaskValidationError("task.scope_invalid") from error
        return posix_path.as_posix()

    @staticmethod
    def _validate_id(value: str, code: str) -> None:
        try:
            ensure_uuid4(value)
        except ValueError as error:
            raise TaskValidationError(code) from error


def task_fingerprint(
    request: TaskRequest,
    *,
    parent_task_id: TaskId | None,
    workspace_revision: str,
) -> str:
    payload = {
        "parent_task_id": None if parent_task_id is None else str(parent_task_id),
        "request": request.model_dump(mode="json"),
        "workspace_revision": workspace_revision.strip(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalize_text(value: str) -> str:
    return " ".join(value.split())
