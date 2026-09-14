from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CatalogSource(StrEnum):
    DISCOVERED = "discovered"
    MAINTAINED = "maintained"
    EVALUATED = "evaluated"
    USER = "user"


class CatalogEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    provider: str
    model: str
    source: CatalogSource
    as_of: datetime
    trusted: bool
    fields: dict[str, Any] = Field(default_factory=dict)
