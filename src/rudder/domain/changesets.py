"""Versioned evidence contracts for future isolated-workspace integration."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rudder.domain.ids import ensure_uuid4

SUPPORTED_CHANGESET_SCHEMA_VERSION = 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _validate_relative_path(value: str) -> str:
    if value.startswith("/") or "\\" in value:
        raise ValueError("changeset.path_invalid")
    parts = value.split("/")
    if any(part in {"", ".", ".."} or ":" in part for part in parts):
        raise ValueError("changeset.path_invalid")
    return value


class ChangeSetStatus(StrEnum):
    CAPTURED = "captured"
    APPLYING = "applying"
    IN_DOUBT = "in_doubt"
    INTEGRATED = "integrated"
    BLOCKED = "blocked"


class ContentImage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    digest: str
    size: int = Field(ge=0)
    artifact_ref: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_digest(self) -> ContentImage:
        if _SHA256.fullmatch(self.digest) is None:
            raise ValueError("changeset.digest_invalid")
        return self


class ChangeSetPath(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(min_length=1)
    effect: str
    file_type: Literal["regular"] = "regular"
    before: ContentImage | None = None
    after: ContentImage | None = None

    @model_validator(mode="after")
    def validate_effect(self) -> ChangeSetPath:
        _validate_relative_path(self.path)
        expected = {
            "added": (None, "image"),
            "modified": ("image", "image"),
            "deleted": ("image", None),
        }.get(self.effect)
        actual = (
            "image" if self.before is not None else None,
            "image" if self.after is not None else None,
        )
        if expected != actual:
            raise ValueError("changeset.effect_images_invalid")
        return self


class ChangeSet(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int
    changeset_id: str
    task_id: str
    attempt_id: str
    snapshot_id: str
    base_head: str
    declared_scope: tuple[str, ...] = Field(min_length=1)
    paths: tuple[ChangeSetPath, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_contract(self) -> ChangeSet:
        if self.schema_version != SUPPORTED_CHANGESET_SCHEMA_VERSION:
            raise ValueError("changeset.schema_unsupported")
        for identifier in (self.changeset_id, self.task_id, self.attempt_id):
            ensure_uuid4(identifier)
        if (
            _SHA256.fullmatch(self.snapshot_id) is None
            or not re.fullmatch(r"[0-9a-f]{40}", self.base_head)
        ):
            raise ValueError("changeset.base_invalid")
        normalized = {
            unicodedata.normalize("NFKC", entry.path).casefold() for entry in self.paths
        }
        if len(normalized) != len(self.paths):
            raise ValueError("changeset.path_collision")
        for scope in self.declared_scope:
            _validate_relative_path(scope)
        for entry in self.paths:
            if not any(
                entry.path == scope or entry.path.startswith(f"{scope}/")
                for scope in self.declared_scope
            ):
                raise ValueError("changeset.path_outside_declared_scope")
        return self

    @property
    def content_digest(self) -> str:
        payload = self.model_dump(mode="json", exclude={"changeset_id"})
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()
