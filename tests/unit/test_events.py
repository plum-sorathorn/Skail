from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from rudder.domain.events import (
    REDACTED,
    BudgetPayload,
    CheckpointPayload,
    DiagnosticPayload,
    EventEnvelope,
    LifecyclePayload,
    ModelPayload,
    RoutePayload,
    SecretRedactor,
    TaskPayload,
    ToolPayload,
    UserPayload,
)
from rudder.domain.ids import (
    new_assignment_id,
    new_attempt_id,
    new_event_id,
    new_run_id,
    new_session_id,
    new_task_id,
)


def _envelope_data(payload: object, *, event_type: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "event_id": new_event_id(),
        "session_id": new_session_id(),
        "run_id": new_run_id(),
        "task_id": new_task_id(),
        "attempt_id": new_attempt_id(),
        "sequence": 1,
        "occurred_at": datetime(2026, 9, 2, 20, 0, tzinfo=UTC),
        "type": event_type,
        "payload": payload,
    }


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        ("session.started", LifecyclePayload(status="started")),
        ("lead.delta", ModelPayload(model="fake-lead", delta="working")),
        ("task.queued", TaskPayload(status="queued", profile="tester")),
        (
            "route.selected",
            RoutePayload(action="selected", assignment_id=str(new_assignment_id())),
        ),
        ("tool.completed", ToolPayload(tool="read_file", status="completed")),
        ("budget.reserved", BudgetPayload(action="reserved", amount_usd=Decimal("0.0250"))),
        (
            "checkpoint.created",
            CheckpointPayload(action="created", checkpoint_id="checkpoint-1"),
        ),
        ("user.question", UserPayload(action="question", content="Proceed?")),
        (
            "invariant.failed",
            DiagnosticPayload(code="runtime.invariant", summary="Invariant failed"),
        ),
    ],
)
def test_each_required_payload_family_round_trips_with_its_concrete_type(
    event_type: str,
    payload: object,
) -> None:
    event = EventEnvelope.model_validate(_envelope_data(payload, event_type=event_type))

    restored = EventEnvelope.from_json(event.to_json())

    assert restored == event
    assert type(restored.payload) is type(payload)
    assert restored.model_dump(mode="json")["payload"]["family"] == payload.family  # type: ignore[attr-defined,index]


def test_event_decimal_amount_uses_a_string_at_the_json_boundary() -> None:
    event = EventEnvelope.model_validate(
        _envelope_data(
            BudgetPayload(action="charged", amount_usd=Decimal("0.0100")),
            event_type="budget.charged",
        )
    )

    assert event.model_dump(mode="json")["payload"]["amount_usd"] == "0.0100"  # type: ignore[index]
    assert '"amount_usd":"0.0100"' in event.to_json()


def test_unknown_schema_version_is_rejected() -> None:
    data = _envelope_data(LifecyclePayload(status="started"), event_type="run.started")
    data["schema_version"] = 2

    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(data)


@pytest.mark.parametrize(
    "missing",
    [
        "event_id",
        "session_id",
        "run_id",
        "sequence",
        "type",
        "payload",
    ],
)
def test_envelope_rejects_missing_identity_sequence_type_or_payload(missing: str) -> None:
    data = _envelope_data(TaskPayload(status="started"), event_type="task.started")
    del data[missing]

    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(data)


@pytest.mark.parametrize(
    "payload",
    [
        {"family": "future-family", "status": "started"},
        {"status": "started"},
        {"family": "task", "action": "selected"},
    ],
)
def test_payload_discriminator_rejects_unknown_missing_or_wrong_family_shape(
    payload: dict[str, str],
) -> None:
    data = _envelope_data(payload, event_type="task.started")

    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(data)


def test_event_type_cannot_be_paired_with_an_unrelated_payload_family() -> None:
    data = _envelope_data(
        BudgetPayload(action="reserved", amount_usd=Decimal("0.01")),
        event_type="task.started",
    )

    with pytest.raises(ValidationError, match="payload family task"):
        EventEnvelope.model_validate(data)


def test_unknown_event_type_is_rejected() -> None:
    data = _envelope_data(TaskPayload(status="future"), event_type="task.future_state")

    with pytest.raises(ValidationError, match="unknown event type"):
        EventEnvelope.model_validate(data)


def test_event_type_cannot_contradict_its_payload_state() -> None:
    data = _envelope_data(TaskPayload(status="succeeded"), event_type="task.started")

    with pytest.raises(ValidationError, match="conflicts with payload state"):
        EventEnvelope.model_validate(data)


def test_diagnostic_payload_redacts_nested_secret_fields_before_storage_or_export() -> None:
    canary = "rudder-canary-secret-value"
    payload = DiagnosticPayload(
        code="provider.protocol_error",
        summary="Provider rejected the request",
        details={
            "api_key": canary,
            "nested": {
                "authorization": canary,
                "safe": "retained",
                "items": [{"token": canary}],
            },
        },
    )
    event = EventEnvelope.model_validate(
        _envelope_data(payload, event_type="diagnostic.error")
    )

    exported = event.to_json()

    assert canary not in exported
    assert payload.details["api_key"] == REDACTED
    assert payload.details["nested"]["authorization"] == REDACTED  # type: ignore[index]
    assert payload.details["nested"]["items"][0]["token"] == REDACTED  # type: ignore[index]
    assert payload.details["nested"]["safe"] == "retained"  # type: ignore[index]


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        (
            "diagnostic.error",
            DiagnosticPayload(code="provider.error", summary="secret-canary"),
        ),
        ("lead.delta", ModelPayload(model="fake", delta="secret-canary")),
        ("user.answer", UserPayload(action="answer", content="secret-canary")),
    ],
)
def test_registered_secret_values_are_scrubbed_from_all_event_text(
    event_type: str, payload: object
) -> None:
    event = EventEnvelope.model_validate(_envelope_data(payload, event_type=event_type))

    exported = event.to_json(SecretRedactor(["secret-canary"]))

    assert "secret-canary" not in exported
    assert REDACTED in exported
