from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable

from rudder.domain.usage import NormalizedUsage, UsageAuthority
from rudder.providers.base import ModelOptions, ModelProfile, ProviderSupportLevel
from rudder.providers.catalog_sources import CatalogEntry
from rudder.providers.errors import ProviderError, ProviderErrorKind


class DeterministicFakeChatModel(BaseChatModel):
    """Deterministic offline fake chat model supporting tool binding."""

    model_name: str = "fake:model"
    response_text: str = "Task completed successfully by Rudder fake provider."

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        last_content = ""
        for m in reversed(messages):
            if m.type == "human" and m.content:
                last_content = str(m.content)
                break
        content = self.response_text or f"Rudder executed: {last_content}"
        generation = ChatGeneration(message=AIMessage(content=content))
        return ChatResult(generations=[generation])

    @property
    def _llm_type(self) -> str:
        return "rudder-deterministic-fake"

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[Any, AIMessage]:
        return self


class FakeProviderAdapter:
    name: str = "fake"
    support_level: ProviderSupportLevel = ProviderSupportLevel.NATIVE

    def __init__(self, model: BaseChatModel | None = None) -> None:
        self.model = model or DeterministicFakeChatModel()

    def validate_config(self, config: object) -> None:
        del config

    def create_model(self, model: ModelProfile, options: ModelOptions) -> BaseChatModel:
        del options
        return self.model

    async def discover_models(self) -> tuple[CatalogEntry, ...]:
        return ()

    def normalize_usage(self, response: object) -> NormalizedUsage | None:
        if not isinstance(response, BaseMessage):
            return None
        usage_meta = getattr(response, "usage_metadata", None)
        if isinstance(usage_meta, dict):
            in_tokens = int(usage_meta.get("input_tokens", 10))
            out_tokens = int(usage_meta.get("output_tokens", 20))
        else:
            in_tokens = 10
            out_tokens = 20
        raw_cost = Decimal("0.001")
        resp_meta = getattr(response, "response_metadata", {})
        if isinstance(resp_meta, dict) and "rudder_cost_usd" in resp_meta:
            raw_cost = Decimal(str(resp_meta["rudder_cost_usd"]))
        return NormalizedUsage(
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            cost_usd=raw_cost,
            authority=UsageAuthority.AUTHORITATIVE_ACTUAL,
        )

    def classify_error(self, error: Exception) -> ProviderError:
        return ProviderError(
            kind=ProviderErrorKind.PROTOCOL,
            summary=str(error),
            provider=self.name,
            retry_safe=False,
        )


__all__ = ["DeterministicFakeChatModel", "FakeProviderAdapter"]

