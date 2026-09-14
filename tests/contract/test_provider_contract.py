from __future__ import annotations

from decimal import Decimal

import pytest
from fakes.provider import FakeInjectedProviderFailure, FakeProviderAdapter, FakeProviderChatModel
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, ValidationError

from skail.domain.usage import UsageAuthority
from skail.providers.base import ModelOptions, ModelProfile, ProviderSupportLevel
from skail.providers.errors import ProviderErrorKind
from skail.providers.factory import ModelFactory, ModelFactoryKey


class StructuredAnswer(BaseModel):
    answer: str
    confidence: int


def _profile() -> ModelProfile:
    return ModelProfile(
        provider="fake",
        model="fake/capable",
        support_level=ProviderSupportLevel.NATIVE,
    )


def test_provider_support_levels_do_not_collapse_distinct_claims() -> None:
    assert {level.value for level in ProviderSupportLevel} == {
        "native",
        "openai-compatible",
        "manual",
        "unverified",
    }


def test_model_factory_key_is_immutable_hashable_and_contains_no_resolved_secret() -> None:
    key = ModelFactoryKey(
        provider="fake",
        model="fake/capable",
        base_url=None,
        credential_reference="FAKE_PROVIDER_API_KEY",
        options=(("temperature", "0"),),
    )

    assert hash(key) == hash(key)
    assert "FAKE_PROVIDER_API_KEY" in repr(key)
    assert "resolved-fixture-credential" not in repr(key)
    assert not hasattr(key, "api_key")
    with pytest.raises((AttributeError, ValidationError)):
        key.model = "fake/replaced"  # type: ignore[misc]


def test_model_factory_reuses_only_an_identical_safe_key() -> None:
    factory = ModelFactory()
    base_key = ModelFactoryKey(
        provider="fake",
        model="fake/capable",
        base_url=None,
        credential_reference="FAKE_PROVIDER_API_KEY",
        options=(("temperature", "0"),),
    )
    changed_key = ModelFactoryKey(
        provider="fake",
        model="fake/capable",
        base_url=None,
        credential_reference="FAKE_PROVIDER_API_KEY",
        options=(("temperature", "0.2"),),
    )
    created: list[object] = []

    def build() -> object:
        instance = object()
        created.append(instance)
        return instance

    first = factory.get_or_create(base_key, build)
    same = factory.get_or_create(base_key, build)
    changed = factory.get_or_create(changed_key, build)

    assert same is first
    assert changed is not first
    assert len(created) == 2


def test_fake_provider_supports_text_streaming_and_normalized_usage() -> None:
    fake = FakeProviderAdapter(
        FakeProviderChatModel(
            response_text="complete",
            stream_parts=("com", "plete"),
            input_tokens=13,
            output_tokens=5,
            cost_usd=Decimal("0.000021"),
        )
    )
    model = fake.create_model(_profile(), ModelOptions())

    response = model.invoke([HumanMessage(content="finish the task")])
    streamed = "".join(str(chunk.content) for chunk in model.stream("stream the task"))
    usage = fake.normalize_usage(response)

    assert response.content == "complete"
    assert streamed == "complete"
    assert usage is not None
    assert usage.input_tokens == 13
    assert usage.output_tokens == 5
    assert usage.cost_usd == Decimal("0.000021")
    assert usage.authority is UsageAuthority.AUTHORITATIVE_ACTUAL


def test_fake_provider_supports_tools() -> None:
    fake = FakeProviderAdapter(
        FakeProviderChatModel(
            tool_call={
                "name": "read_file",
                "args": {"path": "README.md"},
                "id": "fake-tool-1",
                "type": "tool_call",
            }
        )
    )
    model = fake.create_model(_profile(), ModelOptions())
    bound = model.bind_tools(
        [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read one file",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                },
            }
        ]
    )

    response = bound.invoke("read the project readme")

    assert fake.model.bound_tool_names == frozenset({"read_file"})
    assert response.tool_calls == [
        {
            "name": "read_file",
            "args": {"path": "README.md"},
            "id": "fake-tool-1",
            "type": "tool_call",
        }
    ]


def test_fake_provider_supports_structured_output() -> None:
    fake = FakeProviderAdapter(
        FakeProviderChatModel(structured_value={"answer": "ready", "confidence": 9})
    )
    model = fake.create_model(_profile(), ModelOptions())

    response = model.with_structured_output(StructuredAnswer).invoke("report status")

    assert response == StructuredAnswer(answer="ready", confidence=9)


@pytest.mark.parametrize(
    ("kind", "retry_safe"),
    [
        (ProviderErrorKind.AUTHENTICATION, False),
        (ProviderErrorKind.RATE_LIMIT, True),
        (ProviderErrorKind.TRANSIENT, True),
        (ProviderErrorKind.INVALID_MODEL, False),
        (ProviderErrorKind.PROTOCOL, False),
    ],
)
def test_fake_provider_injects_and_normalizes_declared_failures(
    kind: ProviderErrorKind,
    retry_safe: bool,
) -> None:
    fake = FakeProviderAdapter(FakeProviderChatModel(failures=[kind]))
    model = fake.create_model(_profile(), ModelOptions())

    with pytest.raises(FakeInjectedProviderFailure) as raised:
        model.invoke("fail deterministically")

    normalized = fake.classify_error(raised.value)
    assert normalized.kind is kind
    assert normalized.retry_safe is retry_safe
    assert normalized.provider == "fake"
