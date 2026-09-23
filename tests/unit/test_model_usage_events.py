"""D-12(1) telemetry: model.completed carries provider usage; accounting untouched.

Usage fields are observability only — record_call / settle_attempt and the
ledger stay the single journaled source of truth. Providers that report
nothing keep the two-argument event exactly as before.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from skail.domain.events import EventPayload, ModelPayload
from skail.domain.usage import NormalizedUsage, UsageAuthority
from skail.providers.langchain import LangChainUsageAdapter
from skail.tools.assembly import RuntimeActivityMiddleware


def _usage() -> NormalizedUsage:
    return NormalizedUsage(
        input_tokens=11,
        output_tokens=5,
        cost_usd=Decimal("0.25"),
        authority=UsageAuthority.AUTHORITATIVE_ACTUAL,
    )


class _Emit:
    """Arity-tolerant emitter capturing every positional call."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def __call__(self, *args: object) -> None:
        self.calls.append(args)


def test_model_payload_accepts_optional_usage() -> None:
    payload = ModelPayload(
        model="lead",
        input_tokens=10,
        output_tokens=4,
        cost_usd=0.5,
        usage_authority=UsageAuthority.AUTHORITATIVE_ACTUAL.value,
    )

    assert payload.input_tokens == 10
    assert payload.output_tokens == 4
    assert payload.cost_usd == 0.5
    assert payload.usage_authority == "authoritative_actual"


def test_model_payload_usage_fields_default_to_none() -> None:
    payload = ModelPayload(model="lead", delta="working")

    assert payload.input_tokens is None
    assert payload.output_tokens is None
    assert payload.cost_usd is None
    assert payload.usage_authority is None


def test_model_payload_stays_frozen_and_extra_forbid() -> None:
    payload = ModelPayload(model="lead")

    with pytest.raises(ValidationError):
        ModelPayload(model="lead", unexpected=1)
    with pytest.raises(ValidationError):
        payload.model = "other"


def test_normalized_usage_maps_into_payload_telemetry() -> None:
    usage = NormalizedUsage(
        input_tokens=7,
        output_tokens=3,
        cost_usd=Decimal("0.0125"),
        authority=UsageAuthority.ESTIMATED_ACTUAL,
    )

    payload = ModelPayload(
        model="lead",
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=float(usage.cost_usd),
        usage_authority=usage.authority.value,
    )

    assert payload.input_tokens == 7
    assert payload.output_tokens == 3
    assert payload.cost_usd == 0.0125
    assert payload.usage_authority == "estimated_actual"


def test_langchain_usage_preserves_tokens_without_inventing_zero_cost() -> None:
    response = AIMessage(
        content="hi",
        usage_metadata={"input_tokens": 120, "output_tokens": 8, "total_tokens": 128},
    )

    usage = LangChainUsageAdapter("fixture").normalize_usage(response)

    assert usage is not None
    assert (usage.input_tokens, usage.output_tokens) == (120, 8)
    assert usage.cost_usd is None
    assert usage.authority is UsageAuthority.TOKEN_DERIVED_ESTIMATE


def test_missing_cost_is_distinct_from_reported_zero() -> None:
    missing = NormalizedUsage(
        input_tokens=1,
        output_tokens=1,
        cost_usd=None,
        authority=UsageAuthority.TOKEN_DERIVED_ESTIMATE,
    )
    reported_zero = NormalizedUsage(
        input_tokens=1,
        output_tokens=1,
        cost_usd=Decimal("0"),
        authority=UsageAuthority.AUTHORITATIVE_ACTUAL,
    )

    assert missing.cost_usd is None
    assert reported_zero.cost_usd == Decimal("0")
    assert missing.authority is not reported_zero.authority


def test_wrap_model_call_emits_usage_on_model_completed() -> None:
    emit = _Emit()
    middleware = RuntimeActivityMiddleware(
        model_name="lead-model",
        emit=emit,
        redactor=None,
        usage_normalizer=lambda _response: _usage(),
    )

    middleware.wrap_model_call(SimpleNamespace(), lambda _request: SimpleNamespace())

    assert emit.calls[0] == ("model.started", "lead-model")
    completed = emit.calls[1]
    assert completed[:2] == ("model.completed", "lead-model")
    usage = completed[2]
    assert isinstance(usage, NormalizedUsage)
    assert (usage.input_tokens, usage.output_tokens) == (11, 5)
    assert usage.authority is UsageAuthority.AUTHORITATIVE_ACTUAL
    assert usage.cost_usd == Decimal("0.25")


def test_wrap_model_call_without_usage_keeps_two_arg_event() -> None:
    emit = _Emit()
    middleware = RuntimeActivityMiddleware(
        model_name="lead-model",
        emit=emit,
        redactor=None,
        usage_normalizer=lambda _response: None,
    )

    middleware.wrap_model_call(SimpleNamespace(), lambda _request: SimpleNamespace())

    assert emit.calls[0] == ("model.started", "lead-model")
    assert emit.calls[1] == ("model.completed", "lead-model")


def test_wrap_model_call_tolerates_two_arg_emitters() -> None:
    calls: list[tuple[str, str]] = []

    def strict_emit(event: str, value: str) -> None:
        calls.append((event, value))

    middleware = RuntimeActivityMiddleware(
        model_name="m",
        emit=strict_emit,
        redactor=None,
        usage_normalizer=lambda _response: _usage(),
    )

    middleware.wrap_model_call(SimpleNamespace(), lambda _request: SimpleNamespace())

    assert calls == [("model.started", "m"), ("model.completed", "m")]


@pytest.mark.asyncio
async def test_awrap_model_call_emits_usage_on_model_completed() -> None:
    emit = _Emit()
    middleware = RuntimeActivityMiddleware(
        model_name="lead-model",
        emit=emit,
        redactor=None,
        usage_normalizer=lambda _response: _usage(),
    )

    async def handler(_request: Any) -> SimpleNamespace:
        return SimpleNamespace()

    await middleware.awrap_model_call(SimpleNamespace(), handler)

    completed = emit.calls[1]
    assert completed[:2] == ("model.completed", "lead-model")
    usage = completed[2]
    assert isinstance(usage, NormalizedUsage)
    assert (usage.input_tokens, usage.output_tokens) == (11, 5)


def test_activity_emitter_maps_model_completed_usage_to_payload() -> None:
    from skail.domain.ids import AttemptId, RunId, TaskId
    from skail.runtime.run_controller import RunController

    controller = RunController.__new__(RunController)
    payloads: list[EventPayload] = []

    def _capture(**kwargs: Any) -> None:
        payloads.append(kwargs["payload"])

    controller._emit_event = _capture  # type: ignore[attr-defined,assignment]
    emitter = RunController._activity_emitter(
        controller,
        run_id=RunId("22222222-2222-4222-8222-222222222222"),
        task_id=TaskId("33333333-3333-4333-8333-333333333333"),
        attempt_id=AttemptId("44444444-4444-4444-8444-444444444444"),
    )

    emitter(
        "model.completed",
        "lead-model",
        NormalizedUsage(
            input_tokens=3,
            output_tokens=9,
            cost_usd=Decimal("0.5"),
            authority=UsageAuthority.ESTIMATED_ACTUAL,
        ),
    )

    assert len(payloads) == 1
    payload = payloads[0]
    assert isinstance(payload, ModelPayload)
    assert payload.model == "lead-model"
    assert (payload.input_tokens, payload.output_tokens) == (3, 9)
    assert payload.cost_usd == 0.5
    assert payload.usage_authority == "estimated_actual"
