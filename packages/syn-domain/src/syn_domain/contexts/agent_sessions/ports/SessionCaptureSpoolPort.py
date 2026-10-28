"""Durable recovery work projected from pre-launch session capture intent."""

from collections.abc import Collection
from typing import Literal, Protocol, Self

from pydantic import Field, model_validator

from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    InventoryModel,
    RoutingIdentifier,
    RunIdentity,
)

SpoolBackend = Literal["docker", "e2b"]
"""Where the staged bytes live, so a worker can route recovery from the row alone."""

CaptureProfile = Literal["local-spool/1", "sandbox-spool/1"]
"""The capture contract a session is planned with, fixed when it starts."""


def capture_profile_for(backend: SpoolBackend) -> CaptureProfile:
    """A Docker spool is a host volume; every remote one is on its sandbox's disk."""
    return "local-spool/1" if backend == "docker" else "sandbox-spool/1"


class CaptureSpool(InventoryModel):
    """A durable claim on staged capture bytes.

    Docker rows keep their historical shape: a named volume on this host, found
    by run and session. A remote row also names the sandbox holding the spool on
    its own disk and the executor that launched it, so a fresh worker with
    empty memory can reach it.
    """

    run: RunIdentity
    session_id: RoutingIdentifier
    phase_id: RoutingIdentifier
    profile: CaptureProfile = "local-spool/1"
    backend: SpoolBackend = "docker"
    executor_id: RoutingIdentifier | None = None
    sandbox_id: RoutingIdentifier | None = None

    @model_validator(mode="after")
    def _route_matches_backend(self) -> Self:
        remote = self.backend != "docker"
        if remote != (self.profile == "sandbox-spool/1"):
            raise ValueError("Spool profile does not match its backend")
        if remote and (self.sandbox_id is None or self.executor_id is None):
            raise ValueError("A remote spool must name its sandbox and executor")
        if not remote and self.sandbox_id is not None:
            raise ValueError("A Docker spool is a volume, not a sandbox")
        return self


class CaptureSpoolLease(InventoryModel):
    spool: CaptureSpool
    token: int = Field(ge=1)
    after: int = Field(ge=0)
    watermark: int | None = Field(default=None, ge=0)
    child_after: int = Field(default=0, ge=0)
    child_watermark: int | None = Field(default=None, ge=0)
    settled: bool = False
    """The session or run reached a terminal fact before this claim, so no
    executor will resume it. Durable authority to stop a writer that recovery
    finds still alive; never inferred from a disconnected stream."""


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

    async def settle_run(self, run: RunIdentity) -> None:
        """Idempotent projection: the execution reached a terminal fact, so no
        session of it can resume. Settles every spool of the run exactly as
        ``settle`` does; staged bytes still need a complete traversal."""
        ...

    async def claim(
        self, *, lease_seconds: int, backends: Collection[SpoolBackend]
    ) -> CaptureSpoolLease | None:
        """Lease one spool whose backend is in ``backends``: a worker never claims
        a spool it holds no recovery access to. A remote spool is claimed only
        once settled: recovering it stops its writer."""
        ...

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
