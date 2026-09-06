from __future__ import annotations

from enum import StrEnum


class ProviderErrorKind(StrEnum):
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    TRANSIENT = "transient"
    INVALID_MODEL = "invalid_model"
    PROTOCOL = "protocol"


class ProviderError(RuntimeError):
    def __init__(
        self,
        *,
        kind: ProviderErrorKind,
        summary: str,
        provider: str,
        retry_safe: bool,
        provider_code: str | None = None,
    ) -> None:
        self.kind = kind
        self.summary = summary
        self.provider = provider
        self.retry_safe = retry_safe
        self.provider_code = provider_code
        super().__init__(f"provider.{kind.value}: {summary}")


class ProviderDependencyError(RuntimeError):
    def __init__(self, provider: str, package: str, extra: str) -> None:
        self.provider = provider
        self.package = package
        self.install_hint = f'python -m pip install "rudder-harness[{extra}]"'
        super().__init__(f"{provider} requires {package}; install with {self.install_hint}")


class ProviderConfigurationError(ValueError):
    def __init__(self, provider: str, summary: str) -> None:
        self.provider = provider
        super().__init__(f"{provider}: {summary}")
