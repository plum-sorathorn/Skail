from __future__ import annotations

from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from skail.providers.catalog_sources import CatalogEntry


class RoutingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mode: Literal["auto", "economy", "quality", "manual"] = "auto"
    lead_model: str = "auto"
    allow_unmeasured_models: bool = False


class OrchestrationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    delegation: Literal["auto", "ask", "off"] = "auto"
    max_agents: int = Field(default=3, ge=1, le=3)
    max_depth: int = Field(default=1, ge=0, le=1)
    background_agents: bool = False
    workspace_mode: Literal["shared", "worktree"] = "shared"


class BudgetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    run_usd: Decimal | None = Field(default=None, ge=0)
    warning_percent: int = Field(default=80, ge=1, le=100)


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: str
    base_url: str | None = None
    api_key_env: str | None = None
    models: tuple[str, ...] = ()

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        if value is None:
            return value
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("provider base_url must be an absolute HTTP(S) URL")
        return value


class SafetyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_trust: Literal["ask", "trust", "deny"] = "ask"
    write_policy: Literal["allow-workspace", "ask", "deny"] = "allow-workspace"
    command_policy: Literal["ask-dangerous", "ask", "deny"] = "ask-dangerous"


class CatalogConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    entries: tuple[CatalogEntry, ...] = ()


class SkailConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    orchestration: OrchestrationConfig = Field(default_factory=OrchestrationConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    catalog: CatalogConfig = Field(default_factory=CatalogConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)

    @model_validator(mode="after")
    def validate_named_providers(self) -> SkailConfig:
        gateway = self.providers.get("llmgateway")
        if gateway is not None:
            canonical_url = "https://api.llmgateway.io/v1"
            if gateway.base_url is None:
                providers = dict(self.providers)
                providers["llmgateway"] = gateway.model_copy(
                    update={"base_url": canonical_url}
                )
                return self.model_copy(update={"providers": providers})
            if gateway.base_url != canonical_url:
                raise ValueError(f"LLM Gateway base_url must be {canonical_url}")
        return self
