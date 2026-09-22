from __future__ import annotations

import ast
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid1

import pytest
from pydantic import ValidationError

from skail.domain.ids import (
    ReservationId,
    ensure_uuid4,
    new_assignment_id,
    new_attempt_id,
    new_event_id,
    new_plan_id,
    new_plan_node_id,
    new_run_id,
    new_session_id,
    new_task_id,
    new_uuid4,
)
from skail.domain.routing import RoutingMode, TaskAssignment
from skail.domain.tasks import (
    AttemptStatus,
    DomainTransitionError,
    TaskRequest,
    TaskStatus,
    transition_attempt,
    transition_task,
)
from skail.domain.usage import NormalizedUsage, UsageAuthority

ROOT = Path(__file__).resolve().parents[2]
DOMAIN = ROOT / "src" / "skail" / "domain"


@pytest.mark.parametrize(
    "factory",
    [
        new_session_id,
        new_run_id,
        new_task_id,
        new_attempt_id,
        new_assignment_id,
        new_event_id,
        new_plan_id,
        new_plan_node_id,
    ],
)
def test_typed_id_factories_return_canonical_uuid4_strings(factory: Callable[[], str]) -> None:
    value = factory()

    parsed = UUID(value)
    assert isinstance(value, str)
    assert parsed.version == 4
    assert str(parsed) == value


@pytest.mark.parametrize("value", ["not-an-id", str(uuid1())])
def test_uuid4_validation_rejects_noncanonical_or_non_uuid4_values(value: str) -> None:
    with pytest.raises(ValueError):
        ensure_uuid4(value)


def test_uuid4_validation_normalizes_hexadecimal_case() -> None:
    value = new_uuid4()

    assert ensure_uuid4(value.upper()) == value


@pytest.mark.parametrize(
    ("current", "target", "attempt_number"),
    [
        (TaskStatus.PROPOSED, TaskStatus.QUEUED, 1),
        (TaskStatus.QUEUED, TaskStatus.RUNNING, 1),
        (TaskStatus.RUNNING, TaskStatus.SUCCEEDED, 1),
        (TaskStatus.RUNNING, TaskStatus.FAILED, 1),
        (TaskStatus.FAILED, TaskStatus.QUEUED, 1),
        (TaskStatus.FAILED, TaskStatus.RETURNED_TO_LEAD, 2),
        (TaskStatus.RUNNING, TaskStatus.BLOCKED, 1),
        (TaskStatus.RUNNING, TaskStatus.BUDGET_BLOCKED, 1),
        (TaskStatus.RUNNING, TaskStatus.CANCELLED, 1),
    ],
)
def test_task_state_machine_accepts_legal_transitions(
    current: TaskStatus,
    target: TaskStatus,
    attempt_number: int,
) -> None:
    assert transition_task(current, target, attempt_number=attempt_number) is target


@pytest.mark.parametrize(
    ("current", "target", "attempt_number"),
    [
        (TaskStatus.PROPOSED, TaskStatus.RUNNING, 1),
        (TaskStatus.QUEUED, TaskStatus.SUCCEEDED, 1),
        (TaskStatus.FAILED, TaskStatus.QUEUED, 2),
        (TaskStatus.SUCCEEDED, TaskStatus.QUEUED, 1),
        (TaskStatus.CANCELLED, TaskStatus.RUNNING, 1),
    ],
)
def test_task_state_machine_rejects_illegal_transitions(
    current: TaskStatus,
    target: TaskStatus,
    attempt_number: int,
) -> None:
    with pytest.raises(DomainTransitionError, match="transition|attempt"):
        transition_task(current, target, attempt_number=attempt_number)


@pytest.mark.parametrize(
    "terminal",
    [
        TaskStatus.SUCCEEDED,
        TaskStatus.RETURNED_TO_LEAD,
        TaskStatus.BLOCKED,
        TaskStatus.BUDGET_BLOCKED,
        TaskStatus.CANCELLED,
    ],
)
def test_duplicate_terminal_task_transition_is_idempotent(terminal: TaskStatus) -> None:
    assert transition_task(terminal, terminal) is terminal


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (AttemptStatus.ASSIGNED, AttemptStatus.RUNNING),
        (AttemptStatus.RUNNING, AttemptStatus.SUCCEEDED),
        (AttemptStatus.RUNNING, AttemptStatus.FAILED),
        (AttemptStatus.RUNNING, AttemptStatus.BLOCKED),
        (AttemptStatus.RUNNING, AttemptStatus.CANCELLED),
        (AttemptStatus.RUNNING, AttemptStatus.INTERRUPTED),
    ],
)
def test_attempt_state_machine_accepts_legal_transitions(
    current: AttemptStatus,
    target: AttemptStatus,
) -> None:
    assert transition_attempt(current, target) is target


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (AttemptStatus.ASSIGNED, AttemptStatus.SUCCEEDED),
        (AttemptStatus.SUCCEEDED, AttemptStatus.RUNNING),
        (AttemptStatus.FAILED, AttemptStatus.ASSIGNED),
        (AttemptStatus.INTERRUPTED, AttemptStatus.RUNNING),
    ],
)
def test_attempt_state_machine_rejects_illegal_transitions(
    current: AttemptStatus,
    target: AttemptStatus,
) -> None:
    with pytest.raises(DomainTransitionError, match="illegal attempt transition"):
        transition_attempt(current, target)


@pytest.mark.parametrize(
    "terminal",
    [
        AttemptStatus.SUCCEEDED,
        AttemptStatus.FAILED,
        AttemptStatus.BLOCKED,
        AttemptStatus.CANCELLED,
        AttemptStatus.INTERRUPTED,
    ],
)
def test_duplicate_terminal_attempt_transition_is_idempotent(terminal: AttemptStatus) -> None:
    assert transition_attempt(terminal, terminal) is terminal


def _assignment(*, attempt_number: int = 1) -> TaskAssignment:
    return TaskAssignment(
        assignment_id=new_assignment_id(),
        task_id=new_task_id(),
        attempt_number=attempt_number,  # type: ignore[arg-type]
        provider="fake",
        model="fake-capable",
        routing_mode=RoutingMode.AUTO,
        capability_floor=0.5,
        estimated_attempt_cost_usd=Decimal("0.0100"),
        reservation_id=ReservationId(new_uuid4()),
        explanation=("lowest qualifying estimated cost",),
        catalog_revision="fixture-1",
    )


@pytest.mark.parametrize("attempt_number", [1, 2])
def test_assignment_is_immutable_and_limited_to_two_attempts(attempt_number: int) -> None:
    assignment = _assignment(attempt_number=attempt_number)

    with pytest.raises(ValidationError, match="frozen"):
        assignment.model = "silently-substituted"  # type: ignore[misc]


@pytest.mark.parametrize("attempt_number", [0, 3])
def test_assignment_rejects_attempts_outside_the_two_attempt_limit(
    attempt_number: int,
) -> None:
    with pytest.raises(ValidationError):
        _assignment(attempt_number=attempt_number)


def test_money_serializes_as_decimal_strings_without_float_rounding() -> None:
    assignment = _assignment()
    request = TaskRequest(description="Inspect one concern", budget_usd=Decimal("2.5000"))
    usage = NormalizedUsage(
        input_tokens=13,
        output_tokens=8,
        cost_usd=Decimal("0.00012300"),
        authority=UsageAuthority.AUTHORITATIVE_ACTUAL,
    )

    assert assignment.model_dump(mode="json")["estimated_attempt_cost_usd"] == "0.0100"
    assert request.model_dump(mode="json")["budget_usd"] == "2.5000"
    assert usage.model_dump(mode="json")["cost_usd"] == "0.00012300"
    assert '"estimated_attempt_cost_usd":"0.0100"' in assignment.model_dump_json()


def test_domain_modules_do_not_import_framework_ui_provider_or_database_packages() -> None:
    forbidden_roots = {
        "deepagents",
        "langchain",
        "langgraph",
        "textual",
        "sqlite3",
        "aiosqlite",
        "sqlalchemy",
    }
    violations: list[str] = []

    for path in DOMAIN.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported: tuple[str, ...] = ()
            if isinstance(node, ast.Import):
                imported = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = (node.module,)
            for module in imported:
                root = module.split(".", maxsplit=1)[0]
                if (
                    root in forbidden_roots
                    or module.startswith("skail.providers")
                    or module.startswith("skail.sessions")
                ):
                    violations.append(f"{path.relative_to(ROOT)} imports {module}")

    assert violations == []
