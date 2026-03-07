"""Tests for PositionCheckpoint."""

from __future__ import annotations

from typing import Any

import pytest

from syn_adapters.subscriptions.position_checkpoint import PositionCheckpoint


class MockProjectionStore:
    """Mock projection store for testing."""

    def __init__(self) -> None:
        self._positions: dict[str, int] = {}
        self._data: dict[str, dict[str, Any]] = {}

    async def get_position(self, key: str) -> int | None:
        return self._positions.get(key)

    async def set_position(self, key: str, position: int) -> None:
        self._positions[key] = position

    async def get_all(self, projection_name: str) -> list[dict[str, Any]]:
        return list(self._data.get(projection_name, {}).values())


@pytest.fixture
def store() -> MockProjectionStore:
    return MockProjectionStore()


@pytest.mark.unit
class TestPositionCheckpoint:
    @pytest.mark.asyncio
    async def test_load_returns_zero_when_no_position(self, store: MockProjectionStore) -> None:
        cp = PositionCheckpoint(store, "test_key")
        pos = await cp.load()
        assert pos == 0

    @pytest.mark.asyncio
    async def test_save_and_load(self, store: MockProjectionStore) -> None:
        cp = PositionCheckpoint(store, "test_key")
        await cp.save(42)
        pos = await cp.load()
        assert pos == 42
        assert cp.last_save_time is not None

    @pytest.mark.asyncio
    async def test_validate_consistency_no_drift(self, store: MockProjectionStore) -> None:
        store._data["workflow_executions"] = {"e1": {"id": "e1"}}
        cp = PositionCheckpoint(store, "test_key")
        # Should not raise
        await cp.validate_consistency(100)

    @pytest.mark.asyncio
    async def test_validate_consistency_drift_detected(self, store: MockProjectionStore) -> None:
        # Empty projections with high position — drift scenario
        cp = PositionCheckpoint(store, "test_key")
        # Should log critical but not raise
        await cp.validate_consistency(100)

    @pytest.mark.asyncio
    async def test_validate_consistency_skips_zero(self, store: MockProjectionStore) -> None:
        cp = PositionCheckpoint(store, "test_key")
        # Should return immediately
        await cp.validate_consistency(0)
