"""Only a fully drained page can advance the durable capture cursor."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from syn_adapters.session_inventory.recovery_worker import CaptureRecoveryWorker
from syn_adapters.session_inventory.spool_drain import SpoolDrainProgress
from syn_domain.contexts.agent_sessions import CaptureSpool, CaptureSpoolLease, RunIdentity

pytestmark = pytest.mark.unit


class Recovery:
    @asynccontextmanager
    async def open(self, spool):
        yield "reader"


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
