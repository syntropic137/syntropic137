"""Session inventory API models, re-exported through the shared API type surface."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.agent_sessions import (
    InventoryFilter,
    InventoryItem,
    InventoryItemKeys,
    InventoryNode,
    InventorySnapshot,
    ItemKind,
    RunIdentity,
    TranscriptBodyState,
)


class SessionInventoryResponse(BaseModel):
    """Published inventory and observed reconstruction progress, without read side effects."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    run: RunIdentity
    snapshot: InventorySnapshot | None
    reconstruction_status: Literal["not_started", "pending", "running", "current", "failed"]
    observed_evidence_watermark: int = Field(ge=0)
    later_evidence_pending: bool
    job_id: str | None = None


class SessionInventoryPageResponse(BaseModel):
    """One keyset page of a pinned revision plus current local restrictions.

    ``item_keys[i]`` names the qualified node keys ``items[i]`` references, so an
    edge endpoint on another page resolves through the node lookup route.
    ``next_cursor`` is opaque and bound to this run, revision, section and filters.
    Absent body overrides are unchecked.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    snapshot: InventorySnapshot
    kind: ItemKind
    filters: InventoryFilter
    items: tuple[InventoryItem, ...]
    item_keys: tuple[InventoryItemKeys, ...]
    next_cursor: str | None = None
    body_overrides: tuple[TranscriptBodyState, ...] = ()


class SessionInventoryCursorError(BaseModel):
    """Why a continuation cursor was refused. ``restart`` means re-read the head."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    code: Literal["cursor_invalid", "cursor_mismatch", "cursor_expired"]
    message: str
    mismatched: tuple[Literal["scope", "revision", "section", "filters"], ...] = ()
    restart: bool
    restart_snapshot_id: str | None = None


class SessionInventoryCursorErrorResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    detail: SessionInventoryCursorError


class SessionInventoryNodeResponse(BaseModel):
    """A node-by-key lookup within one revision. Unknown keys disclose nothing."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    snapshot_id: str
    node_key: str
    status: Literal["resolved", "unresolved"]
    node: InventoryNode | None = None


class SessionInventoryRefreshRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=200, pattern=r"^[^\x00]+$")


class SessionInventoryRefreshResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    job_id: str


class SessionInventoryJobResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    job_id: str
    run: RunIdentity
    stage: Literal["pending", "publishing", "completed", "failed"]
    evidence_watermark: int = Field(ge=0)
    snapshot_id: str
    resolver_version: str
    revision: str | None
    failure_code: str | None


class LocalTranscriptResponse(BaseModel):
    """Exact archive bytes, base64 encoded without parsing provider content."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    status: Literal["present", "not_captured", "missing", "expired", "too_large"]
    archive_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    content_format: Literal["native", "envelope"] | None = None
    size: int | None = Field(default=None, ge=0)
    content_base64: str | None = Field(default=None, repr=False)
