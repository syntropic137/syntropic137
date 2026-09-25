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
    spools.advance.assert_awaited_once_with(
        lease, after=10, watermark=None, retry_seconds=10, staged_bytes=0
    )


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
    spools.advance.assert_awaited_once_with(
        lease, after=20, watermark=None, retry_seconds=10, staged_bytes=0
    )
    children.page.side_effect = None
    children.page.return_value = ChildDrainProgress(watermark=5, next_after=4, persisted=2)
    spools.advance.reset_mock()
    assert await worker.step()
    assert children.page.await_args.kwargs["after"] == 2
    assert children.page.await_args.kwargs["watermark"] == 5
    spools.advance_children.assert_awaited_once_with(lease, after=4, watermark=5)
    spools.advance.assert_awaited_once_with(
        lease, after=20, watermark=None, retry_seconds=0, staged_bytes=0
    )


class ExclusiveRecovery:
    def __init__(self, exclusive: bool) -> None:
        self.exclusive = exclusive
        self.open_now = False

    @asynccontextmanager
    async def open(self, spool):
        self.open_now = True
        try:
            yield RecoveryReaders(
                transcripts=AsyncMock(), children=AsyncMock(), exclusive=self.exclusive
            )
        finally:
            self.open_now = False


def _lease() -> CaptureSpoolLease:
    return CaptureSpoolLease(
        spool=CaptureSpool(
            run=RunIdentity(source_instance_id="source", execution_id="run"),
            session_id="session",
            phase_id="phase",
        ),
        token=3,
        after=0,
    )


@pytest.mark.parametrize("exclusive", [True, False])
async def test_complete_traversal_marks_drained_then_offers_release_after_helper_exits(
    exclusive: bool,
) -> None:
    lease = _lease()
    spools, drain, release = AsyncMock(), AsyncMock(), AsyncMock()
    spools.claim.return_value = lease
    drain.page.return_value = SpoolDrainProgress(
        watermark=4, next_after=None, captured=4, staged_bytes=900
    )
    recovery = ExclusiveRecovery(exclusive)

    async def after_drain(value, *, exclusive):
        # The helper container must be gone, or its mount would block removal.
        assert not recovery.open_now
        return exclusive

    release.after_drain.side_effect = after_drain
    worker = CaptureRecoveryWorker(
        spools, recovery, drain, lease_seconds=120, retry_seconds=10, release=release
    )
    assert await worker.step()
    spools.advance.assert_awaited_once_with(
        lease, after=4, watermark=None, retry_seconds=10, staged_bytes=900
    )
    spools.mark_drained.assert_awaited_once_with(lease)
    release.after_drain.assert_awaited_once_with(lease, exclusive=exclusive)


@pytest.mark.parametrize("case", ["more_pages", "child_failed", "child_more", "capture_failed"])
async def test_incomplete_traversal_never_marks_drained_or_releases(case: str) -> None:
    from syn_adapters.session_inventory.child_journal import ChildDrainProgress

    lease = _lease()
    spools, drain, children, release = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    spools.claim.return_value = lease
    drain.page.return_value = SpoolDrainProgress(
        watermark=8, next_after=4 if case == "more_pages" else None, captured=4
    )
    if case == "capture_failed":
        drain.page.side_effect = OSError("archive unavailable")
    children.page.return_value = ChildDrainProgress(
        watermark=5, next_after=2 if case == "child_more" else None, persisted=2
    )
    if case == "child_failed":
        children.page.side_effect = OSError("journal unavailable")
    worker = CaptureRecoveryWorker(
        spools,
        ExclusiveRecovery(True),
        drain,
        children=children,
        lease_seconds=120,
        retry_seconds=10,
        release=release,
    )
    assert await worker.step()
    spools.mark_drained.assert_not_awaited()
    release.after_drain.assert_not_awaited()
