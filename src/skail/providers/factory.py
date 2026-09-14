from __future__ import annotations

from collections.abc import Callable
from threading import RLock
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModelFactoryKey(BaseModel):
    model_config = ConfigDict(frozen=True)
    provider: str
    model: str
    base_url: str | None
    credential_reference: str
    credential_fingerprint: str = Field(default="unversioned", repr=False)
    options: tuple[tuple[str, str], ...] = ()

    @model_validator(mode="after")
    def reject_secret_options(self) -> ModelFactoryKey:
        sensitive = {"api_key", "apikey", "authorization", "password", "secret", "token"}
        for name, _ in self.options:
            if name.lower() in sensitive:
                raise ValueError(f"secret option {name} cannot enter a model factory key")
        return self

    def __hash__(self) -> int:
        return hash(
            (
                self.provider,
                self.model,
                self.base_url,
                self.credential_reference,
                self.credential_fingerprint,
                self.options,
            )
        )


class ModelFactory:
    def __init__(self) -> None:
        self._instances: dict[ModelFactoryKey, Any] = {}
        self._lock = RLock()

    def get_or_create(self, key: ModelFactoryKey, builder: Callable[[], Any]) -> Any:
        with self._lock:
            if key not in self._instances:
                self._instances[key] = builder()
            return self._instances[key]
