"""Inventory recovery must start live and leave no orphan coordinator on failure."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from syn_api.services import lifecycle
from syn_api.types import Err, Ok

pytestmark = pytest.mark.unit


async def test_inventory_clock_starts_after_subscription_and_before_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    coordinator, runtime = AsyncMock(), AsyncMock()

    async def subscribed() -> None:
        order.append("subscription")

    async def clock() -> None:
        order.append("inventory")

    async def admission() -> None:
        order.append("admission")

    coordinator.start.side_effect = subscribed
    runtime.clock.start.side_effect = clock
    monkeypatch.setattr(lifecycle, "get_realtime", lambda: None)
    monkeypatch.setattr(lifecycle, "get_subscription_coordinator", lambda **_kw: coordinator)
    monkeypatch.setattr(lifecycle, "announce_admission_if_open", admission)
    monkeypatch.setattr("syn_api._wiring_inventory.get_inventory_runtime", lambda: runtime)
    state = lifecycle.LifecycleState(workflow_dispatcher=AsyncMock())
    await lifecycle._init_subscriptions(state)
    assert order == ["subscription", "inventory", "admission"]
    assert state.subscription_service is coordinator


async def test_clock_start_failure_stops_coordinator_before_recovery_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator, runtime = AsyncMock(), AsyncMock()
    runtime.clock.start.side_effect = ConnectionError("event store unavailable")
    monkeypatch.setattr(lifecycle, "get_realtime", lambda: None)
    monkeypatch.setattr(lifecycle, "get_subscription_coordinator", lambda **_kw: coordinator)
    monkeypatch.setattr("syn_api._wiring_inventory.get_inventory_runtime", lambda: runtime)
    state = lifecycle.LifecycleState(workflow_dispatcher=AsyncMock())
    with pytest.raises(ConnectionError):
        await lifecycle._init_subscriptions(state)
    coordinator.stop.assert_awaited_once()
    assert state.subscription_service is None


async def test_unavailable_archive_fails_critical_inventory_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initialize = AsyncMock(side_effect=PermissionError("archive cannot be written"))
    monkeypatch.setattr("syn_api._wiring_inventory.initialize_inventory_runtime", initialize)
    assert isinstance(await lifecycle.inventory_lifecycle.initialize_session_inventory(), Err)


async def test_startup_abort_names_the_inventory_failure_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#1511: the abort line is all that survives a restart loop, so it carries the cause."""
    initialize = AsyncMock(side_effect=PermissionError("/app/data/session-inventory not writable"))
    monkeypatch.setattr("syn_api._wiring_inventory.initialize_inventory_runtime", initialize)
    monkeypatch.setattr(lifecycle, "_init_import_ledger", AsyncMock(return_value=Ok(None)))
    monkeypatch.setattr(lifecycle, "start_request_latency", AsyncMock())
    monkeypatch.setattr("syn_api._wiring_db.init_shared_db_pool", AsyncMock())
    result = await lifecycle._init_durable_stores()
    assert isinstance(result, Err)
    assert "PermissionError: /app/data/session-inventory not writable" in result.message
