from __future__ import annotations

import importlib.util
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from rudder.providers.errors import ProviderConfigurationError


@dataclass(frozen=True)
class ProviderRegistration:
    name: str
    module: str
    package: str
    extra: str
    contract_tested: bool
    auto_routing_eligible: bool
    maintained_ci: bool
    allowed_options: frozenset[str]


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    installed: bool
    constructible: bool
    contract_tested: bool
    auto_routing_eligible: bool
    maintained_ci: bool


class LangChainProviderRegistry:
    def __init__(
        self,
        *,
        registrations: Iterable[ProviderRegistration],
        package_probe: Callable[[str], bool] | None = None,
    ) -> None:
        values = tuple(registrations)
        self._registrations = {value.name: value for value in values}
        if len(self._registrations) != len(values):
            raise ValueError("duplicate provider registration")
        self._package_probe = package_probe or (
            lambda module: importlib.util.find_spec(module) is not None
        )

    def registration(self, name: str) -> ProviderRegistration:
        try:
            return self._registrations[name]
        except KeyError as exc:
            raise ProviderConfigurationError(name, "provider is not registered") from exc

    def status(self, name: str) -> ProviderStatus:
        registration = self.registration(name)
        installed = self._package_probe(registration.module)
        return ProviderStatus(
            name=name,
            installed=installed,
            constructible=installed,
            contract_tested=registration.contract_tested,
            auto_routing_eligible=registration.auto_routing_eligible,
            maintained_ci=registration.maintained_ci,
        )

    def is_installed(self, registration: ProviderRegistration) -> bool:
        return self._package_probe(registration.module)
