from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class PermissionSet(BaseModel):
    model_config = ConfigDict(frozen=True)
    read: bool = False
    write: bool = False
    execute: bool = False
    network: bool = False

    def contains(self, requested: PermissionSet) -> bool:
        return all(
            not getattr(requested, name) or getattr(self, name) for name in self.model_fields
        )


class ProjectTrustLevel(StrEnum):
    UNTRUSTED = "untrusted"
    TRUSTED = "trusted"
    DENIED = "denied"


class ProjectExtensionKind(StrEnum):
    CONFIG = "config"
    PROFILE = "profile"
    SKILL = "skill"
    TOOL = "tool"
    MCP = "mcp"
    PROVIDER_REFERENCE = "provider_reference"
    APPROVAL_RULE = "approval_rule"


class WorkspaceIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)
    canonical_path: str
    device: int
    inode: int

    @property
    def key(self) -> str:
        return os.path.normcase(self.canonical_path)


class TrustAssessment(BaseModel):
    model_config = ConfigDict(frozen=True)
    level: ProjectTrustLevel
    requires_prompt: bool
    reason: str

    def permits(self, kind: ProjectExtensionKind) -> bool:
        del kind
        return self.level is ProjectTrustLevel.TRUSTED


def identify_workspace(path: Path) -> WorkspaceIdentity:
    canonical = path.resolve(strict=True)
    if not canonical.is_dir():
        raise ValueError("workspace must be a directory")
    stat = canonical.stat()
    return WorkspaceIdentity(
        canonical_path=str(canonical),
        device=int(stat.st_dev),
        inode=int(stat.st_ino),
    )
