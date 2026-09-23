"""Expiry failures cannot stop capture recovery or inventory reconstruction."""

from unittest.mock import AsyncMock

import pytest

from syn_adapters.session_inventory.runtime import _InventoryWork
from syn_shared.settings.session_inventory import SessionInventorySettings

pytestmark = pytest.mark.unit


async def test_expiry_failure_does_not_block_inventory_work():
    retention, recovery, scheduler = AsyncMock(), AsyncMock(), AsyncMock()
    retention.step.side_effect = OSError("storage unavailable")
    work = _InventoryWork(
        scheduler=scheduler, step=AsyncMock(), recovery=recovery, retention=retention
    )
    await work.schedule()
    recovery.step.assert_awaited_once()
    scheduler.handle.assert_awaited_once()


def test_expiry_requires_explicit_positive_configuration():
    assert SessionInventorySettings(_env_file=None).local_body_retention_seconds is None
    assert (
        SessionInventorySettings(
            _env_file=None, local_body_retention_seconds=86400
        ).local_body_retention_seconds
        == 86400
    )
    with pytest.raises(ValueError):
        SessionInventorySettings(_env_file=None, local_body_retention_seconds=0)
