"""Expiry failures cannot stop capture recovery or inventory reconstruction."""

from unittest.mock import AsyncMock

import pytest

from syn_adapters.session_inventory.runtime import InventoryWork
from syn_shared.settings.session_inventory import SessionInventorySettings

pytestmark = pytest.mark.unit


async def test_expiry_failure_does_not_block_inventory_work(caplog):
    retention, recovery, scheduler = AsyncMock(), AsyncMock(), AsyncMock()
    spool_release = AsyncMock()
    retention.drain.side_effect = OSError("/private/archive/secret-token-123")
    spool_release.step.side_effect = RuntimeError("secret-token-456")
    work = InventoryWork(
        scheduler=scheduler,
        step=AsyncMock(),
        recovery=recovery,
        retention=retention,
        spool_release=spool_release,
    )
    await work.schedule()
    recovery.step.assert_awaited_once()
    scheduler.handle.assert_awaited_once()
    # Diagnostics name the failure class only: no paths, tokens or payloads.
    assert "OSError" in caplog.text and "RuntimeError" in caplog.text
    assert "secret-token" not in caplog.text and "/private/archive" not in caplog.text


def test_quotas_are_disabled_by_default_and_must_be_positive():
    settings = SessionInventorySettings(_env_file=None)
    assert settings.local_body_max_bytes is None
    assert settings.spool_retention_seconds is None
    assert settings.spool_max_bytes is None
    assert settings.spool_settle_grace_seconds == 86400
    for field in ("local_body_max_bytes", "spool_retention_seconds", "spool_max_bytes"):
        with pytest.raises(ValueError):
            SessionInventorySettings.model_validate({field: 0})
    with pytest.raises(ValueError):
        SessionInventorySettings.model_validate({"spool_settle_grace_seconds": 59})


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
