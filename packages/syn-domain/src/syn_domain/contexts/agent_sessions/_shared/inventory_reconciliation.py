"""Management state, never workflow execution or billing state (#1398)."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID  # noqa: TC003 - Pydantic runtime field

from pydantic import Field

from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    Identifier,
    InventoryModel,
    RunIdentity,
)


class ReconciliationStage(StrEnum):
    PENDING = "pending"
    PUBLISHING = "publishing"
    COMPLETED = "completed"
    FAILED = "failed"


class ReconciliationRequest(InventoryModel):
    run: RunIdentity
    evidence_watermark: int = Field(ge=0)
    expected_head: UUID | None
    snapshot_id: UUID
    resolver_version: Identifier


class ReconciliationState(InventoryModel):
    request: ReconciliationRequest
    stage: ReconciliationStage = ReconciliationStage.PENDING
    revision: str | None = None
    failure_code: Identifier | None = None
