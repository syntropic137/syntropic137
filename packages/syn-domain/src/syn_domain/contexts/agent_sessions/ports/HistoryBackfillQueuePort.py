"""Durable to-do list for bulk historical backfill; processed only by the live worker."""

from __future__ import annotations

from typing import Protocol

from pydantic import Field

from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    Identifier,
    InventoryModel,
    RunIdentity,
)


class HistoryBackfillItem(InventoryModel):
    run: RunIdentity
    idempotency_key: Identifier = Field(max_length=200)


class HistoryBackfillLease(InventoryModel):
    item: HistoryBackfillItem
    lease_token: int = Field(ge=1)
    attempts: int = Field(ge=1)


class HistoryBackfillQueuePort(Protocol):
    async def enqueue(self, items: tuple[HistoryBackfillItem, ...]) -> int:
        """Idempotent per (run, key). Returns how many were newly queued."""
        ...

    async def claim(self, *, lease_seconds: int) -> HistoryBackfillLease | None: ...

    async def complete(self, lease: HistoryBackfillLease, job_id: str) -> None: ...

    async def retry(self, lease: HistoryBackfillLease, *, retry_seconds: int) -> None: ...

    async def fail(self, lease: HistoryBackfillLease, failure_code: str) -> None: ...
