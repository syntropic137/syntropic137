"""#2107 S5: /health reports what the confirmed-expiry gate keeps, by reason."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, get_args
from unittest.mock import AsyncMock

import pytest

from syn_adapters.session_inventory.expiry_gate import ExpiryHold
from syn_adapters.session_inventory.expiry_holds import ExpiryHoldCount
from syn_api import _wiring_inventory
from syn_api.services import health_probes
from syn_api.types import SessionExpiryHoldCount, SessionExpiryHoldReason, SessionStoreHealth

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_measure = health_probes._measure_session_store


@dataclass(frozen=True)
class _Runtime:
    expiry_holds: AsyncMock | None


def test_the_api_reason_list_is_exactly_the_gate_hold_reasons() -> None:
    assert set(get_args(SessionExpiryHoldReason)) == {hold.value for hold in ExpiryHold}


def test_totals_and_operator_line() -> None:
    health = health_probes.expiry_holds_health(
        [
            SessionExpiryHoldCount(hold="older_revision", bodies=30, bytes=3 << 20),
            SessionExpiryHoldCount(hold="unavailable", bodies=2, bytes=1 << 20),
        ]
    )
    assert (health.held_bodies, health.held_bytes) == (32, 4 << 20)
    assert "older_revision 30 (3.0 MiB)" in health.detail
    assert "unavailable 2 (1.0 MiB)" in health.detail
    assert health_probes.expiry_holds_health([]).detail == "expiry gate keeps nothing"


async def _refreshed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, runtime: _Runtime
) -> SessionStoreHealth | None:
    (tmp_path / ("a" * 64)).write_bytes(b"x")
    cache = health_probes._SessionStoreCache()
    monkeypatch.setattr(health_probes, "_session_store_cache", cache)
    monkeypatch.setattr(
        health_probes, "_measure_session_store", lambda _root, now: _measure(tmp_path, now)
    )
    monkeypatch.setattr(_wiring_inventory, "get_inventory_runtime", lambda: runtime)
    await health_probes.describe_session_store()
    assert cache.refresh is not None
    await cache.refresh
    return cache.value


async def test_the_session_store_block_carries_the_holds_when_the_gate_is_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    holds = AsyncMock()
    holds.summary.return_value = [
        ExpiryHoldCount(hold=ExpiryHold.SPLICE_BASE, bodies=3, bytes=900),
        ExpiryHoldCount(hold=ExpiryHold.NO_BACKUP_ATTESTATION, bodies=1, bytes=100),
    ]
    value = await _refreshed(monkeypatch, tmp_path, _Runtime(expiry_holds=holds))
    assert value is not None and value.expiry_holds is not None
    assert [(c.hold, c.bodies, c.bytes) for c in value.expiry_holds.by_hold] == [
        ("splice_base", 3, 900),
        ("no_backup_attestation", 1, 100),
    ]
    assert (value.expiry_holds.held_bodies, value.expiry_holds.held_bytes) == (4, 1000)


async def test_no_holds_block_when_the_gate_is_off_or_unreadable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = await _refreshed(monkeypatch, tmp_path, _Runtime(expiry_holds=None))
    assert value is not None and value.expiry_holds is None
    failing = AsyncMock()
    failing.summary.side_effect = OSError("db down")
    value = await _refreshed(monkeypatch, tmp_path, _Runtime(expiry_holds=failing))
    assert value is not None and value.expiry_holds is None
