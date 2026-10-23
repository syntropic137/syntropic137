"""Live-only recovery; projection merely registers durable spool work."""

from __future__ import annotations

import logging
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from syn_domain.contexts.agent_sessions import CaptureSpoolLeaseLost

if TYPE_CHECKING:
    from collections.abc import Mapping
    from contextlib import AbstractAsyncContextManager

    from agentic_isolation.child_journal import WorkspaceChildJournalReader
    from agentic_isolation.session_spool import WorkspaceSpoolReader

    from syn_domain.contexts.agent_sessions import (
        CaptureSpool,
        CaptureSpoolLease,
        SessionCaptureSpoolPort,
        SpoolBackend,
    )

    from .child_journal import ChildJournalDrain
    from .spool_drain import LocalSpoolDrain

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecoveryReaders:
    transcripts: WorkspaceSpoolReader
    children: WorkspaceChildJournalReader
    exclusive: bool = False
    """Nothing else could write during this traversal: no other container
    referenced the volume, or the provider confirmed no agent process remains
    in the sandbox. Never inferred from a run state or a disconnected stream.
    Release requires it."""


class SpoolReleasePort(Protocol):
    async def after_drain(self, lease: CaptureSpoolLease, *, exclusive: bool) -> bool:
        """Release staged bytes a complete traversal archived; False keeps them."""
        ...


class SpoolRecoveryPort(Protocol):
    def open(self, spool: CaptureSpool) -> AbstractAsyncContextManager[RecoveryReaders]:
        """Reopen the retained spool and capture retained native files before reading."""
        ...


class CaptureRecoveryWorker:
    def __init__(
        self,
        spools: SessionCaptureSpoolPort,
        recovery: Mapping[SpoolBackend, SpoolRecoveryPort],
        drain: LocalSpoolDrain,
        *,
        lease_seconds: int,
        retry_seconds: int,
        children: ChildJournalDrain | None = None,
        release: Mapping[SpoolBackend, SpoolReleasePort] | None = None,
    ) -> None:
        """``recovery`` names every backend this worker can reach; it claims
        only those spools. A backend with no ``release`` entry keeps its bytes."""
        if not recovery:
            raise ValueError("A recovery worker needs at least one backend")
        self._spools, self._recovery, self._drain = spools, recovery, drain
        self._children = children
        self._release = release or {}
        self._lease_seconds, self._retry_seconds = lease_seconds, retry_seconds

    async def step(self) -> bool:
        lease = await self._spools.claim(
            lease_seconds=self._lease_seconds, backends=tuple(self._recovery)
        )
        if lease is None:
            return False
        try:
            await self._execute(lease)
        except Exception:
            logger.exception("Capture recovery failed; retained spool remains retryable")
            with suppress(CaptureSpoolLeaseLost):
                await self._spools.advance(
                    lease,
                    after=lease.after,
                    watermark=lease.watermark,
                    retry_seconds=self._retry_seconds,
                )
        return True

    async def _execute(self, lease: CaptureSpoolLease) -> None:
        async def renew() -> None:
            await self._spools.renew(lease, lease_seconds=self._lease_seconds)

        async with self._recovery[lease.spool.backend].open(lease.spool) as readers:
            await renew()
            progress = await self._drain.page(
                readers.transcripts,
                run=lease.spool.run,
                spool_id=lease.spool.session_id,
                after=lease.after,
                watermark=lease.watermark,
                renew=renew,
            )
            children = await self._recover_children(lease, readers)
            await self._spools.advance(
                lease,
                after=progress.next_after
                if progress.next_after is not None
                else progress.watermark,
                watermark=progress.watermark if progress.next_after is not None else None,
                retry_seconds=0
                if progress.next_after is not None or children == "more"
                else self._retry_seconds,
                staged_bytes=progress.staged_bytes,
            )
            complete = progress.next_after is None and children == "complete"
        # Release after the helper container is gone: its mount would block removal.
        # A remote sandbox stays paused until this point; release kills it.
        if complete:
            await self._spools.mark_drained(lease)
            release = self._release.get(lease.spool.backend)
            if release is not None:
                await release.after_drain(lease, exclusive=readers.exclusive)

    async def _recover_children(
        self, lease: CaptureSpoolLease, readers: RecoveryReaders
    ) -> Literal["complete", "more", "failed"]:
        """ "complete" only when a child traversal finished during this lease."""
        if self._children is None:
            return "complete"
        try:
            await self._spools.renew(lease, lease_seconds=self._lease_seconds)
            progress = await self._children.page(
                readers.children,
                run=lease.spool.run,
                spool_id=lease.spool.session_id,
                observation_sequence=lease.token,
                after=lease.child_after,
                watermark=lease.child_watermark,
            )
            await self._spools.advance_children(
                lease,
                after=progress.next_after
                if progress.next_after is not None
                else progress.watermark,
                watermark=progress.watermark if progress.next_after is not None else None,
            )
            return "complete" if progress.next_after is None else "more"
        except CaptureSpoolLeaseLost:
            raise
        except Exception:
            # Transcript and child sequences are independent. Retain the child
            # cursor for retry while allowing durable transcript work to advance.
            logger.exception("Child journal recovery failed; child cursor remains retryable")
            return "failed"
