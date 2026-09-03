from __future__ import annotations

from typing import Any

import pytest
from fakes.provider import FakeInjectedProviderFailure, FakeProviderAdapter, FakeProviderChatModel
from langchain.agents.middleware import ModelRequest
from langchain_core.messages import AIMessage

from rudder.providers.errors import ProviderError, ProviderErrorKind
from rudder.providers.fallback import FallbackBinding, ProviderFallbackPolicy
from rudder.runtime.model_middleware import TaskBoundModelMiddleware


def _state() -> dict[str, Any]:
    return {
        "messages": [],
        "current_assignment_id": "assignment-a",
        "locked_assignment_id": "assignment-a",
        "assigned_provider": "fake",
        "assigned_model": "primary",
        "reservation_id": "reservation-a",
        "attempt_id": "attempt-1",
    }


def test_retryable_transport_failure_uses_one_recorded_equivalent_fallback() -> None:
    primary = FakeProviderChatModel(model_name="primary")
    fallback = FakeProviderChatModel(model_name="fallback")
    created: list[tuple[str, ProviderErrorKind]] = []
    settled: list[str] = []

    def create(previous: str, error: ProviderError) -> FallbackBinding:
        created.append((previous, error.kind))
        return FallbackBinding(
            assignment_id="assignment-b",
            provider="backup",
            model="primary",
            model_key="fallback",
            reservation_id="reservation-b",
        )

    middleware = TaskBoundModelMiddleware(
        {"primary": primary, "fallback": fallback},
        assignments={"assignment-a": "primary"},
        providers={"fake": FakeProviderAdapter(primary)},
        fallback_policy=ProviderFallbackPolicy(
            {("fake", "primary"): create}, is_persisted=lambda binding: True
        ),
        usage_callback=lambda assignment_id, response, call_id: settled.append(assignment_id),
    )
    calls: list[str] = []

    def handler(request: ModelRequest[Any]) -> Any:
        calls.append(request.state["current_assignment_id"])
        if len(calls) == 1:
            raise FakeInjectedProviderFailure(ProviderErrorKind.RATE_LIMIT)
        assert request.model is fallback
        return AIMessage(content="ok")

    state = _state()
    response = middleware.wrap_model_call(
        ModelRequest(model=primary, messages=[], state=state), handler
    )
    assert response.content == "ok"
    assert calls == ["assignment-a", "assignment-b"]
    assert created == [("assignment-a", ProviderErrorKind.RATE_LIMIT)]
    assert settled == ["assignment-b"]
    assert state["current_assignment_id"] == "assignment-b"
    assert state["locked_assignment_id"] == "assignment-b"


def test_provider_fallback_cannot_disguise_model_escalation() -> None:
    error = ProviderError(
        kind=ProviderErrorKind.TRANSIENT,
        summary="outage",
        provider="fake",
        retry_safe=True,
    )
    policy = ProviderFallbackPolicy(
        {
            ("fake", "primary"): lambda previous, failure: FallbackBinding(
                assignment_id="assignment-b",
                provider="backup",
                model="stronger-model",
                model_key="stronger",
                reservation_id="reservation-b",
            )
        },
        is_persisted=lambda binding: True,
    )
    with pytest.raises(ValueError, match="preserve the concrete model"):
        policy.fallback_for(
            provider="fake", model="primary", assignment_id="assignment-a", error=error
        )


def test_provider_fallback_cannot_use_an_unpersisted_assignment() -> None:
    error = ProviderError(
        kind=ProviderErrorKind.TRANSIENT,
        summary="outage",
        provider="fake",
        retry_safe=True,
    )
    binding = FallbackBinding(
        assignment_id="assignment-b",
        provider="backup",
        model="primary",
        model_key="fallback",
        reservation_id="reservation-b",
    )
    policy = ProviderFallbackPolicy(
        {("fake", "primary"): lambda previous, failure: binding},
        is_persisted=lambda candidate: False,
    )
    with pytest.raises(ValueError, match="persisted before use"):
        policy.fallback_for(
            provider="fake", model="primary", assignment_id="assignment-a", error=error
        )


@pytest.mark.parametrize(
    "kind", [ProviderErrorKind.AUTHENTICATION, ProviderErrorKind.INVALID_MODEL]
)
def test_authentication_and_invalid_model_fail_without_fallback(kind: ProviderErrorKind) -> None:
    primary = FakeProviderChatModel(model_name="primary")
    fallback_calls: list[str] = []
    middleware = TaskBoundModelMiddleware(
        {"primary": primary},
        assignments={"assignment-a": "primary"},
        providers={"fake": FakeProviderAdapter(primary)},
        fallback_policy=ProviderFallbackPolicy(
            {
                ("fake", "primary"): lambda previous, error: fallback_calls.append(previous)  # type: ignore[dict-item]
            },
            is_persisted=lambda binding: True,
        ),
    )
    with pytest.raises(ProviderError) as caught:
        middleware.wrap_model_call(
            ModelRequest(model=primary, messages=[], state=_state()),
            lambda request: (_ for _ in ()).throw(FakeInjectedProviderFailure(kind)),
        )
    assert caught.value.kind is kind
    assert fallback_calls == []


def test_healthy_call_never_consults_fallback_policy() -> None:
    primary = FakeProviderChatModel(model_name="primary")
    fallback_calls: list[str] = []
    middleware = TaskBoundModelMiddleware(
        {"primary": primary},
        assignments={"assignment-a": "primary"},
        providers={"fake": FakeProviderAdapter(primary)},
        fallback_policy=ProviderFallbackPolicy(
            {
                ("fake", "primary"): lambda previous, error: fallback_calls.append(previous)  # type: ignore[dict-item]
            },
            is_persisted=lambda binding: True,
        ),
    )
    response = middleware.wrap_model_call(
        ModelRequest(model=primary, messages=[], state=_state()),
        lambda request: AIMessage(content="healthy"),
    )
    assert response.content == "healthy"
    assert fallback_calls == []
