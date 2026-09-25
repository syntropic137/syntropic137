"""Durable recovery work projected from pre-launch session capture intent."""

from typing import Literal, Protocol

from pydantic import Field

from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    InventoryModel,
    RoutingIdentifier,
    RunIdentity,
)


class CaptureSpool(InventoryModel):
    run: RunIdentity
    session_id: RoutingIdentifier
    phase_id: RoutingIdentifier
    profile: Literal["local-spool/1"] = "local-spool/1"


class CaptureSpoolLease(InventoryModel):
    spool: CaptureSpool
    token: int = Field(ge=1)
    after: int = Field(ge=0)
    watermark: int | None = Field(default=None, ge=0)
    child_after: int = Field(default=0, ge=0)
    child_watermark: int | None = Field(default=None, ge=0)


class CaptureSpoolLeaseLost(Exception):
    """Another worker owns this spool; the stale worker cannot advance it."""


class SessionCaptureSpoolPort(Protocol):
    async def project(self, spool: CaptureSpool) -> None:
        """Idempotent projection only. Never run capture while replaying."""
        ...

    async def settle(self, session_id: str) -> None:
        """Idempotent projection: the platform session finished, so no new workspace
        is launched for it. Staged bytes still need a complete traversal."""
        ...

    async def claim(self, *, lease_seconds: int) -> CaptureSpoolLease | None: ...

    async def renew(self, lease: CaptureSpoolLease, *, lease_seconds: int) -> None: ...

    async def advance(
        self,
        lease: CaptureSpoolLease,
        *,
        after: int,
        watermark: int | None,
        retry_seconds: int,
        staged_bytes: int = 0,
    ) -> None:
        """Persist only a fully archived and journaled page, under a live lease.

        ``staged_bytes`` adds the spool bytes this page read to the retained total.
        """
        ...

    async def mark_drained(self, lease: CaptureSpoolLease) -> None:
        """Record that a complete traversal begun under this lease archived every
        staged entry and child record. Only then may staged bytes be released."""
        ...

    async def advance_children(
        self, lease: CaptureSpoolLease, *, after: int, watermark: int | None
    ) -> None:
        """Persist journal progress under the lease without releasing transcript work."""
        ...
