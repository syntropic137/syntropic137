"""Session inventory API models, re-exported through the shared API type surface."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.agent_sessions import InventoryPage, InventorySnapshot, RunIdentity


class SessionInventoryResponse(BaseModel):
    """Published inventory and observed reconstruction progress, without read side effects."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    run: RunIdentity
    snapshot: InventorySnapshot | None
    reconstruction_status: Literal["not_started", "pending", "running", "current", "failed"]
    observed_evidence_watermark: int = Field(ge=0)
    later_evidence_pending: bool
    job_id: str | None = None


class SessionInventoryPageResponse(InventoryPage):
    """A bounded page of one immutable published revision."""


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
    status: Literal["present", "not_captured", "missing", "too_large"]
    archive_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    content_format: Literal["native", "envelope"] | None = None
    size: int | None = Field(default=None, ge=0)
    content_base64: str | None = Field(default=None, repr=False)
