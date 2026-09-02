from __future__ import annotations

from dataclasses import dataclass

SMOKE_RESPONSE = "Rudder fake-provider smoke: ok"


@dataclass(frozen=True)
class FakeProvider:
    """Credential-free provider used only to prove the package boundary."""

    response: str = SMOKE_RESPONSE

    def complete(self, prompt: str) -> str:
        if not prompt:
            raise ValueError("the smoke prompt must not be empty")
        return self.response


def run_fake_provider_smoke() -> str:
    return FakeProvider().complete("health-check")
