"""Only a fully drained page can advance the durable capture cursor."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from syn_adapters.session_inventory.recovery_worker import CaptureRecoveryWorker, RecoveryReaders
from syn_adapters.session_inventory.spool_drain import SpoolDrainProgress
from syn_domain.contexts.agent_sessions import CaptureSpool, CaptureSpoolLease, RunIdentity

pytestmark = pytest.mark.unit


class Recovery:
    @asynccontextmanager
    async def open(self, spool):
        yield RecoveryReaders(transcripts=AsyncMock(), children=AsyncMock())


async def test_failed_page_preserves_cursor_and_success_advances_frozen_watermark() -> None:
    lease = CaptureSpoolLease(
        spool=CaptureSpool(
            run=RunIdentity(source_instance_id="source", execution_id="run"),
            session_id="session",
            phase_id="phase",
        ),
        token=1,
        after=5,
        watermark=10,
    )
    spools = AsyncMock()
    spools.claim.return_value = lease
    drain = AsyncMock()
    drain.page.side_effect = OSError("archive unavailable")
    worker = CaptureRecoveryWorker(spools, Recovery(), drain, lease_seconds=120, retry_seconds=10)
    assert await worker.step()
    spools.advance.assert_awaited_once_with(lease, after=5, watermark=10, retry_seconds=10)
    spools.renew.assert_awaited_once_with(lease, lease_seconds=120)
    spools.advance.reset_mock()
    drain.page.side_effect = None
    drain.page.return_value = SpoolDrainProgress(watermark=10, next_after=None, captured=5)
    assert await worker.step()
    spools.advance.assert_awaited_once_with(lease, after=10, watermark=None, retry_seconds=10)


async def test_no_work_does_not_open_or_drain_a_spool() -> None:
    spools, drain = AsyncMock(), AsyncMock()
    spools.claim.return_value = None
    assert not await CaptureRecoveryWorker(
        spools, Recovery(), drain, lease_seconds=120, retry_seconds=10
    ).step()
    drain.page.assert_not_awaited()


async def test_child_failure_keeps_child_cursor_without_blocking_transcript_progress() -> None:
    from syn_adapters.session_inventory.child_journal import ChildDrainProgress

    lease = CaptureSpoolLease(
        spool=CaptureSpool(
            run=RunIdentity(source_instance_id="source", execution_id="run"),
            session_id="session",
            phase_id="phase",
        ),
        token=1,
        after=10,
        child_after=2,
        child_watermark=5,
    )
    spools, drain, children = AsyncMock(), AsyncMock(), AsyncMock()
    spools.claim.return_value = lease
    drain.page.return_value = SpoolDrainProgress(watermark=20, next_after=None, captured=10)
    children.page.side_effect = OSError("journal unavailable")
    worker = CaptureRecoveryWorker(
        spools,
        Recovery(),
        drain,
        children=children,
        lease_seconds=120,
        retry_seconds=10,
    )
    assert await worker.step()
    spools.advance_children.assert_not_awaited()
    spools.advance.assert_awaited_once_with(lease, after=20, watermark=None, retry_seconds=10)
    children.page.side_effect = None
    children.page.return_value = ChildDrainProgress(watermark=5, next_after=4, persisted=2)
    spools.advance.reset_mock()
    assert await worker.step()
    assert children.page.await_args.kwargs["after"] == 2
    assert children.page.await_args.kwargs["watermark"] == 5
    spools.advance_children.assert_awaited_once_with(lease, after=4, watermark=5)
    spools.advance.assert_awaited_once_with(lease, after=20, watermark=None, retry_seconds=0)
