from __future__ import annotations

from decimal import Decimal

import pytest

from rudder.agents.profile_loader import AgentProfile
from rudder.agents.profiles import builtin_profiles
from rudder.domain.ids import new_run_id
from rudder.domain.security import PermissionSet as ProfilePermissionSet
from rudder.domain.tasks import ModelConstraint, TaskRequest
from rudder.runtime.task_validation import TaskValidationError, TaskValidator


def _validator(tmp_path, *, max_description_chars: int = 20_000) -> TaskValidator:
    return TaskValidator(
        profiles=builtin_profiles(),
        workspace_root=tmp_path,
        max_depth=1,
        background_enabled=False,
        max_description_chars=max_description_chars,
    )


def test_validator_generates_task_identity_and_requirements(tmp_path) -> None:
    validator = _validator(tmp_path)

    spec = validator.create_spec(
        TaskRequest(
            description="  Inspect   the task lifecycle ",
            profile="explorer",
            success_criteria=("Locate the registry",),
        ),
        run_id=new_run_id(),
        parent_task_id=None,
        parent_depth=0,
        workspace_revision="git:abc123",
    )

    assert spec.task_id
    assert spec.depth == 1
    assert spec.requirements.role == "explorer"
    assert spec.requirements.role_hard_min == 0.35
    assert spec.permission_set.read is True
    assert spec.permission_set.write is False
    assert spec.permission_set.execute is False
    assert spec.permission_set.network is False


@pytest.mark.parametrize(
    ("task_request", "parent_depth", "code"),
    [
        (TaskRequest(description="   "), 0, "task.description_empty"),
        (TaskRequest(description="x" * 11), 0, "task.description_oversized"),
        (TaskRequest(description="work", profile="missing"), 0, "task.profile_unknown"),
        (TaskRequest(description="work"), 1, "task.depth_exceeded"),
        (TaskRequest(description="work", depends_on=("not-an-id",)), 0, "task.dependency_invalid"),
        (TaskRequest(description="work", write_scope=("../outside",)), 0, "task.scope_invalid"),
        (
            TaskRequest(description="work", profile="explorer", write_scope=("src",)),
            0,
            "task.scope_forbidden",
        ),
        (TaskRequest(description="work", background=True), 0, "task.background_disabled"),
    ],
)
def test_validator_reports_stable_rejection_codes(
    tmp_path,
    task_request: TaskRequest,
    parent_depth: int,
    code: str,
) -> None:
    validator = _validator(tmp_path, max_description_chars=10)

    with pytest.raises(TaskValidationError, match=f"^{code}$"):
        validator.create_spec(
            task_request,
            run_id=new_run_id(),
            parent_task_id=None,
            parent_depth=parent_depth,
            workspace_revision="git:abc123",
        )


def test_fingerprint_normalizes_request_and_includes_workspace_revision(tmp_path) -> None:
    validator = _validator(tmp_path)
    first = validator.create_spec(
        TaskRequest(
            description="Inspect   a file",
            profile="implementer",
            success_criteria=("Find  the symbol",),
            write_scope=("src\\rudder",),
        ),
        run_id=new_run_id(),
        parent_task_id=None,
        parent_depth=0,
        workspace_revision="git:abc123",
    )
    equivalent = validator.create_spec(
        TaskRequest(
            description=" Inspect a file ",
            profile="implementer",
            success_criteria=("Find the symbol",),
            write_scope=("src/rudder",),
        ),
        run_id=new_run_id(),
        parent_task_id=None,
        parent_depth=0,
        workspace_revision="git:abc123",
    )
    changed_workspace = validator.create_spec(
        equivalent.request,
        run_id=new_run_id(),
        parent_task_id=None,
        parent_depth=0,
        workspace_revision="git:def456",
    )

    assert first.fingerprint == equivalent.fingerprint
    assert first.fingerprint != changed_workspace.fingerprint


def test_validator_uses_trusted_budget_and_model_policy_instead_of_task_text(tmp_path) -> None:
    validator = _validator(tmp_path)
    spec = validator.create_spec(
        TaskRequest(
            description="Inspect the registry",
            budget_usd=Decimal("99"),
            model_policy=ModelConstraint(provider="untrusted", model="expensive"),
        ),
        run_id=new_run_id(),
        parent_task_id=None,
        parent_depth=0,
        workspace_revision="git:abc123",
        budget_usd=Decimal("2.50"),
        model_policy=ModelConstraint(provider="trusted", model="approved"),
    )

    assert spec.request.budget_usd == Decimal("2.50")
    assert spec.request.model_policy == ModelConstraint(provider="trusted", model="approved")


def test_validator_preserves_profile_network_permission_and_stable_profile_errors(tmp_path) -> None:
    profiles = builtin_profiles()
    validator = TaskValidator(
        profiles=profiles,
        workspace_root=tmp_path,
        max_depth=1,
        background_enabled=False,
    )
    researcher = validator.create_spec(
        TaskRequest(description="Read the documentation", profile="researcher"),
        run_id=new_run_id(),
        parent_task_id=None,
        parent_depth=0,
        workspace_revision="git:abc123",
    )
    profiles["invalid"] = AgentProfile(
        name="invalid",
        description="invalid",
        role="not-a-routing-role",
        tools=(),
        permissions=ProfilePermissionSet(read=True),
        prompt="invalid",
        source="test",
        revision="test",
    )

    assert researcher.permission_set.network is True
    with pytest.raises(TaskValidationError, match="^task.profile_invalid$"):
        validator.create_spec(
            TaskRequest(description="invalid", profile="invalid"),
            run_id=new_run_id(),
            parent_task_id=None,
            parent_depth=0,
            workspace_revision="git:abc123",
        )
