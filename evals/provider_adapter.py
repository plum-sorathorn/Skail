from __future__ import annotations

from decimal import Decimal

from langchain_core.messages import BaseMessage

from skail.domain.usage import NormalizedUsage, UsageAuthority
from skail.providers.errors import ProviderError, ProviderErrorKind
from skail.providers.models import ProviderSupportLevel


class EvaluationUsageAdapter:
    """Normalize usage emitted by deterministic evaluation fixtures."""

    name = "eval-provider"
    support_level = ProviderSupportLevel.NATIVE

    def normalize_usage(self, response: object) -> NormalizedUsage | None:
        if not isinstance(response, BaseMessage) or response.usage_metadata is None:
            return None
        raw_cost = response.response_metadata.get("skail_cost_usd")
        return NormalizedUsage(
            input_tokens=response.usage_metadata["input_tokens"],
            output_tokens=response.usage_metadata["output_tokens"],
            cost_usd=Decimal(str(raw_cost)) if raw_cost is not None else None,
            authority=(
                UsageAuthority.AUTHORITATIVE_ACTUAL
                if raw_cost is not None
                else UsageAuthority.TOKEN_DERIVED_ESTIMATE
            ),
        )

    def classify_error(self, error: Exception) -> ProviderError:
        return ProviderError(
            kind=ProviderErrorKind.PROTOCOL,
            summary=str(error),
            provider=self.name,
            retry_safe=False,
        )
