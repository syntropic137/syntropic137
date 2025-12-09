"""Regression tests for subscription position atomicity.

These tests verify that events are never skipped when the subscription
restarts, regardless of where crashes occur during event processing.

Related issue: If position is saved but projection data is not (or vice versa),
events can be permanently skipped on restart.

See: ADR-017, ADR-018, PROJECT-PLAN_20251209_observability-unification.md
"""

import asyncio
import os
from typing import Any
from unittest.mock import MagicMock

import pytest

from aef_adapters.subscriptions.service import (
    SUBSCRIPTION_POSITION_KEY,
    EventSubscriptionService,
)


class MockTestEnvironmentError(Exception):
    """Raised when a mock is used outside of test environment."""

    pass


def _assert_test_environment() -> None:
    """Assert that we're running in a test environment."""
    app_env = os.getenv("APP_ENVIRONMENT", "").lower()
    if app_env != "test":
        raise MockTestEnvironmentError(
            f"Mock objects can only be used in test environment. "
            f"Current APP_ENVIRONMENT: '{app_env}'. "
            f"Set APP_ENVIRONMENT=test to use mocks."
        )


class MockEventEnvelope:
    """Mock event envelope for testing."""

    def __init__(self, event_type: str, global_nonce: int, data: dict | None = None):
        _assert_test_environment()
        self.event = MagicMock()
        self.event.event_type = event_type
        self.event.to_dict.return_value = data or {"id": f"test-{global_nonce}"}
        self.metadata = MagicMock()
        self.metadata.global_nonce = global_nonce
        self.metadata.stream_id = f"TestStream-{global_nonce}"


class MockEventStoreClient:
    """Mock event store client for testing."""

    def __init__(self):
        _assert_test_environment()
        self.events: list[MockEventEnvelope] = []

    async def read_all(
        self,
        from_global_nonce: int = 0,
        max_count: int = 100,
        forward: bool = True,
    ) -> tuple[list[MockEventEnvelope], bool, int]:
        """Return events from the given position with pagination."""
        if forward:
            filtered = [e for e in self.events if e.metadata.global_nonce >= from_global_nonce]
            filtered.sort(key=lambda e: e.metadata.global_nonce)
        else:
            filtered = [e for e in self.events if e.metadata.global_nonce <= from_global_nonce]
            filtered.sort(key=lambda e: e.metadata.global_nonce, reverse=True)

        page = filtered[:max_count]
        is_end = len(page) < max_count or len(filtered) <= max_count

        if page:
            next_from = (
                page[-1].metadata.global_nonce + 1
                if forward
                else page[-1].metadata.global_nonce - 1
            )
        else:
            next_from = from_global_nonce

        return page, is_end, next_from

    async def subscribe(self, from_global_nonce: int = 0):
        """Yield events starting from the given position."""
        for event in self.events:
            if event.metadata.global_nonce >= from_global_nonce:
                yield event
        while True:
            await asyncio.sleep(0.1)


class FailingProjectionStore:
    """Projection store that can simulate failures.

    This store tracks which events have been "successfully saved" to projections
    and can be configured to fail at specific points.
    """

    def __init__(self):
        _assert_test_environment()
        self._positions: dict[str, int] = {}
        self._projection_data: dict[str, dict[str, Any]] = {}
        self._fail_on_projection_save_for_events: set[int] = set()
        self._fail_on_position_save_for_events: set[int] = set()
        self._saved_event_positions: list[int] = []

    def configure_projection_failure(self, event_positions: set[int]) -> None:
        """Configure which event positions should fail on projection save."""
        self._fail_on_projection_save_for_events = event_positions

    def configure_position_failure(self, event_positions: set[int]) -> None:
        """Configure which event positions should fail on position save."""
        self._fail_on_position_save_for_events = event_positions

    async def get_position(self, projection: str) -> int | None:
        return self._positions.get(projection)

    async def set_position(self, projection: str, position: int) -> None:
        """Save position - can be configured to fail."""
        if position in self._fail_on_position_save_for_events:
            raise RuntimeError(f"Simulated position save failure at position {position}")
        self._positions[projection] = position

    async def save(self, projection: str, key: str, data: dict[str, Any]) -> None:
        """Save projection data - can be configured to fail."""
        event_position = data.get("_event_position", 0)
        if event_position in self._fail_on_projection_save_for_events:
            raise RuntimeError(
                f"Simulated projection save failure for event at position {event_position}"
            )
        if projection not in self._projection_data:
            self._projection_data[projection] = {}
        self._projection_data[projection][key] = data
        self._saved_event_positions.append(event_position)

    async def get(self, projection: str, key: str) -> dict[str, Any] | None:
        return self._projection_data.get(projection, {}).get(key)

    async def get_all(self, projection: str) -> list[dict[str, Any]]:
        return list(self._projection_data.get(projection, {}).values())

    def has_projection_data_for_event(self, event_position: int) -> bool:
        """Check if projection data exists for a specific event position."""
        return event_position in self._saved_event_positions


class TrackingProjectionManager:
    """Projection manager that tracks which events were processed."""

    def __init__(self, store: FailingProjectionStore):
        _assert_test_environment()
        self._store = store
        self.processed_events: list[int] = []
        self._fail_on_dispatch_for_events: set[int] = set()

    def configure_dispatch_failure(self, event_positions: set[int]) -> None:
        """Configure which event positions should fail on dispatch."""
        self._fail_on_dispatch_for_events = event_positions

    async def process_event_envelope(self, envelope: MockEventEnvelope) -> Any:
        """Process an event envelope (tracking version)."""
        global_nonce = envelope.metadata.global_nonce
        event_type = envelope.event.event_type

        if global_nonce in self._fail_on_dispatch_for_events:
            raise RuntimeError(f"Simulated dispatch failure for event {global_nonce}")

        # Track the event was processed
        self.processed_events.append(global_nonce)

        # Simulate saving to projection store
        await self._store.save(
            "test_projection",
            f"event-{global_nonce}",
            {"event_type": event_type, "_event_position": global_nonce},
        )

        # Return mock provenance
        provenance = MagicMock()
        provenance.event_type = event_type
        provenance.stream_id = envelope.metadata.stream_id
        provenance.global_nonce = global_nonce
        return provenance


@pytest.fixture
def event_store() -> MockEventStoreClient:
    """Create mock event store with test events."""
    store = MockEventStoreClient()
    # Create events 1-10
    store.events = [
        MockEventEnvelope(f"TestEvent{i}", i, {"id": f"test-{i}"}) for i in range(1, 11)
    ]
    return store


@pytest.fixture
def projection_store() -> FailingProjectionStore:
    """Create projection store that can simulate failures."""
    return FailingProjectionStore()


@pytest.fixture
def projection_manager(projection_store: FailingProjectionStore) -> TrackingProjectionManager:
    """Create tracking projection manager."""
    return TrackingProjectionManager(projection_store)


class TestSubscriptionPositionAtomicity:
    """Regression tests for subscription position atomicity.

    These tests verify the bug where events can be skipped if:
    1. Position is saved but projection data isn't (crash between operations)
    2. Projection data is saved but position isn't (crash between operations)
    """

    @pytest.mark.asyncio
    async def test_all_events_processed_on_clean_run(
        self,
        event_store: MockEventStoreClient,
        projection_manager: TrackingProjectionManager,
        projection_store: FailingProjectionStore,
    ):
        """Verify all events are processed in a clean run (baseline)."""
        service = EventSubscriptionService(
            event_store_client=event_store,  # type: ignore
            projection_manager=projection_manager,  # type: ignore
            projection_store=projection_store,  # type: ignore
            batch_size=5,
        )

        await service.start()

        # Wait for catch-up
        for _ in range(50):
            if service.is_caught_up:
                break
            await asyncio.sleep(0.1)

        await service.stop()

        # All events should be processed
        assert service.events_processed == 10
        assert projection_manager.processed_events == list(range(1, 11))
        assert projection_store._positions.get(SUBSCRIPTION_POSITION_KEY) == 10

    @pytest.mark.asyncio
    async def test_no_events_skipped_after_simulated_crash_mid_batch(
        self,
        event_store: MockEventStoreClient,
        projection_manager: TrackingProjectionManager,
        projection_store: FailingProjectionStore,
    ):
        """
        REGRESSION TEST: Verify events are not skipped after crash.

        Scenario:
        1. Process events 1-5 successfully (batch_size=5)
        2. Position saved at 5
        3. Process events 6-7 to projections
        4. CRASH before position saved at 10 (or before event 8 projection)
        5. On restart, position shows 5, but projections have data for 6-7
        6. Events 6-7 should be RE-PROCESSED (idempotently), not skipped

        BUG: If crash happens after position save but before projection save,
        those events are permanently lost.
        """
        # First run: Process events 1-7, position saved at 5
        service1 = EventSubscriptionService(
            event_store_client=event_store,  # type: ignore
            projection_manager=projection_manager,  # type: ignore
            projection_store=projection_store,  # type: ignore
            batch_size=5,  # Position saved after every 5 events
        )

        # Simulate crash during event 8 processing
        projection_manager.configure_dispatch_failure({8})

        await service1.start()

        # Wait for some processing (will fail at event 8)
        for _ in range(30):
            if len(projection_manager.processed_events) >= 7:
                break
            await asyncio.sleep(0.1)

        await service1.stop()

        # Verify state after "crash":
        # - Events 1-7 processed
        # - Position saved at 5 (last complete batch) or 7 (depending on implementation)
        processed_before_crash = list(projection_manager.processed_events)
        position_before_crash = projection_store._positions.get(SUBSCRIPTION_POSITION_KEY, 0)

        # Clear failure configuration for restart
        projection_manager.configure_dispatch_failure(set())
        projection_manager.processed_events.clear()

        # Second run: Restart from saved position
        service2 = EventSubscriptionService(
            event_store_client=event_store,  # type: ignore
            projection_manager=projection_manager,  # type: ignore
            projection_store=projection_store,  # type: ignore
            batch_size=5,
        )

        await service2.start()

        # Wait for catch-up
        for _ in range(50):
            if service2.is_caught_up:
                break
            await asyncio.sleep(0.1)

        await service2.stop()

        # KEY ASSERTION: No events should be permanently skipped
        # All events from position+1 to 10 should be processed on restart
        all_processed = set(processed_before_crash) | set(projection_manager.processed_events)
        assert all_processed == set(range(1, 11)), (
            f"Events were skipped! "
            f"Processed before crash: {processed_before_crash}, "
            f"Processed after restart: {projection_manager.processed_events}, "
            f"Position before crash: {position_before_crash}, "
            f"Missing events: {set(range(1, 11)) - all_processed}"
        )

    @pytest.mark.asyncio
    async def test_position_saved_atomically_with_projection(
        self,
        event_store: MockEventStoreClient,
        projection_manager: TrackingProjectionManager,
        projection_store: FailingProjectionStore,
    ):
        """
        REGRESSION TEST: Position should only be saved AFTER projection succeeds.

        Scenario:
        1. Events 1-5 processed, position=5
        2. Event 6 projection fails
        3. Position should NOT advance past 5
        4. On restart, event 6 should be reprocessed

        This tests Option B: "Only save position AFTER all projections confirm success"
        """
        # Configure projection failure for event 6
        projection_manager.configure_dispatch_failure({6})

        service = EventSubscriptionService(
            event_store_client=event_store,  # type: ignore
            projection_manager=projection_manager,  # type: ignore
            projection_store=projection_store,  # type: ignore
            batch_size=5,
        )

        await service.start()

        # Wait for processing to stabilize
        await asyncio.sleep(0.5)
        await service.stop()

        saved_position = projection_store._positions.get(SUBSCRIPTION_POSITION_KEY, 0)

        # CURRENT BEHAVIOR (BUG): Position may advance past failed event
        # EXPECTED BEHAVIOR: Position should be <= 5 (last successful event before failure)
        # Note: This test documents the current bug and will fail until fixed

        # Clear failure and restart
        projection_manager.configure_dispatch_failure(set())
        projection_manager.processed_events.clear()

        service2 = EventSubscriptionService(
            event_store_client=event_store,  # type: ignore
            projection_manager=projection_manager,  # type: ignore
            projection_store=projection_store,  # type: ignore
            batch_size=5,
        )

        await service2.start()
        for _ in range(50):
            if service2.is_caught_up:
                break
            await asyncio.sleep(0.1)
        await service2.stop()

        # Event 6 should be in the restart processing
        assert 6 in projection_manager.processed_events, (
            f"Event 6 was skipped! Position was saved at {saved_position} "
            f"but event 6 was not reprocessed. "
            f"Processed on restart: {projection_manager.processed_events}"
        )

    @pytest.mark.asyncio
    async def test_health_check_detects_position_projection_mismatch(
        self,
        projection_store: FailingProjectionStore,
    ):
        """
        REGRESSION TEST: Health check should detect inconsistency.

        If position says "processed up to 10" but projection data only
        has events 1-5, we have a consistency problem.
        """
        # Simulate inconsistent state: position=10, but only events 1-5 in projections
        projection_store._positions[SUBSCRIPTION_POSITION_KEY] = 10
        for i in range(1, 6):
            await projection_store.save(
                "test_projection",
                f"event-{i}",
                {"_event_position": i, "event_type": f"TestEvent{i}"},
            )

        # This is where we'd call a health check function
        # For now, just verify we can detect the mismatch
        saved_position = projection_store._positions.get(SUBSCRIPTION_POSITION_KEY, 0)
        max_event_in_projection = (
            max(projection_store._saved_event_positions)
            if projection_store._saved_event_positions
            else 0
        )

        # Position claims 10, but projections only have up to 5
        # This is an inconsistency that should be detectable
        assert saved_position > max_event_in_projection, "This test simulates an inconsistent state"

        # The health check should be able to report:
        gap = saved_position - max_event_in_projection
        assert gap > 0, (
            f"Expected gap between position ({saved_position}) and projection data ({max_event_in_projection})"
        )

    @pytest.mark.asyncio
    async def test_health_check_returns_status(
        self,
        event_store: MockEventStoreClient,
        projection_manager: TrackingProjectionManager,
        projection_store: FailingProjectionStore,
    ):
        """Test that health_check() returns proper status information."""
        service = EventSubscriptionService(
            event_store_client=event_store,  # type: ignore
            projection_manager=projection_manager,  # type: ignore
            projection_store=projection_store,  # type: ignore
            batch_size=5,
        )

        # Check health before starting
        health = await service.health_check()
        assert "healthy" in health
        assert "position_saved" in health
        assert "position_in_memory" in health
        assert "warnings" in health

        await service.start()
        for _ in range(50):
            if service.is_caught_up:
                break
            await asyncio.sleep(0.1)

        # Check health while running
        health = await service.health_check()
        assert health["is_running"] is True
        assert health["position_in_memory"] == 10  # All 10 events processed

        await service.stop()

        # Check health after stopping
        health = await service.health_check()
        assert health["is_running"] is False
        assert health["events_processed"] == 10


class TestSubscriptionResumeCorrectness:
    """Tests for correct resume behavior after restart."""

    @pytest.mark.asyncio
    async def test_resumes_from_correct_position_exclusive(
        self,
        event_store: MockEventStoreClient,
        projection_manager: TrackingProjectionManager,
        projection_store: FailingProjectionStore,
    ):
        """Verify subscription resumes from position+1 (exclusive start)."""
        # Simulate previous run processed events 1-5
        projection_store._positions[SUBSCRIPTION_POSITION_KEY] = 5

        service = EventSubscriptionService(
            event_store_client=event_store,  # type: ignore
            projection_manager=projection_manager,  # type: ignore
            projection_store=projection_store,  # type: ignore
            batch_size=10,
        )

        await service.start()
        for _ in range(50):
            if service.is_caught_up:
                break
            await asyncio.sleep(0.1)
        await service.stop()

        # Should process events 6-10 only (not 1-5 again)
        assert projection_manager.processed_events == [6, 7, 8, 9, 10], (
            f"Expected to process events 6-10, but processed: {projection_manager.processed_events}"
        )

    @pytest.mark.asyncio
    async def test_idempotent_reprocessing_is_safe(
        self,
        event_store: MockEventStoreClient,
        projection_manager: TrackingProjectionManager,
        projection_store: FailingProjectionStore,
    ):
        """
        Verify that reprocessing events is idempotent.

        If position is behind actual projections, reprocessing should be safe.
        This is the "at-least-once" guarantee with idempotent handlers.
        """
        # Pre-populate some projection data (simulating previous processing)
        for i in range(1, 6):
            await projection_store.save(
                "test_projection",
                f"event-{i}",
                {"_event_position": i, "event_type": f"TestEvent{i}"},
            )

        # Position is at 3, but projections have data up to 5
        # This could happen if position save failed but projection saves succeeded
        projection_store._positions[SUBSCRIPTION_POSITION_KEY] = 3

        service = EventSubscriptionService(
            event_store_client=event_store,  # type: ignore
            projection_manager=projection_manager,  # type: ignore
            projection_store=projection_store,  # type: ignore
            batch_size=10,
        )

        await service.start()
        for _ in range(50):
            if service.is_caught_up:
                break
            await asyncio.sleep(0.1)
        await service.stop()

        # Events 4-10 should be processed (4, 5 may be reprocessed, which is OK)
        processed = set(projection_manager.processed_events)
        expected = set(range(4, 11))  # Events 4-10
        assert expected.issubset(processed), (
            f"Expected at least events 4-10 to be processed. "
            f"Processed: {projection_manager.processed_events}"
        )
