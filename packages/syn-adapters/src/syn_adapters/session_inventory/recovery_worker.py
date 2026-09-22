"""Live-only recovery; projection merely registers durable spool work."""

from __future__ import annotations

import logging
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from syn_domain.contexts.agent_sessions import CaptureSpoolLeaseLost

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from agentic_isolation.child_journal import WorkspaceChildJournalReader
    from agentic_isolation.session_spool import WorkspaceSpoolReader

    from syn_domain.contexts.agent_sessions import (
        CaptureSpool,
        CaptureSpoolLease,
        SessionCaptureSpoolPort,
    )

    from .child_journal import ChildJournalDrain
    from .spool_drain import LocalSpoolDrain

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecoveryReaders:
    transcripts: WorkspaceSpoolReader
    children: WorkspaceChildJournalReader


class SpoolRecoveryPort(Protocol):
    def open(self, spool: CaptureSpool) -> AbstractAsyncContextManager[RecoveryReaders]:
        """Reopen an existing volume and capture retained native files before reading."""
        ...


class CaptureRecoveryWorker:
    def __init__(
        self,
        spools: SessionCaptureSpoolPort,
        recovery: SpoolRecoveryPort,
        drain: LocalSpoolDrain,
        *,
        lease_seconds: int,
        retry_seconds: int,
        children: ChildJournalDrain | None = None,
    ) -> None:
        self._spools, self._recovery, self._drain = spools, recovery, drain
        self._children = children
        self._lease_seconds, self._retry_seconds = lease_seconds, retry_seconds

    async def step(self) -> bool:
        lease = await self._spools.claim(lease_seconds=self._lease_seconds)
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

        async with self._recovery.open(lease.spool) as readers:
            await renew()
            progress = await self._drain.page(
                readers.transcripts,
                run=lease.spool.run,
                spool_id=lease.spool.session_id,
                after=lease.after,
                watermark=lease.watermark,
                renew=renew,
            )
            child_pending = await self._recover_children(lease, readers)
            await self._spools.advance(
                lease,
                after=progress.next_after
                if progress.next_after is not None
                else progress.watermark,
                watermark=progress.watermark if progress.next_after is not None else None,
                retry_seconds=0
                if progress.next_after is not None or child_pending
                else self._retry_seconds,
            )

    async def _recover_children(self, lease: CaptureSpoolLease, readers: RecoveryReaders) -> bool:
        if self._children is None:
            return False
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
            return progress.next_after is not None
        except CaptureSpoolLeaseLost:
            raise
        except Exception:
            # Transcript and child sequences are independent. Retain the child
            # cursor for retry while allowing durable transcript work to advance.
            logger.exception("Child journal recovery failed; child cursor remains retryable")
            return False
