"""Tests for EventSubscriptionService."""

import asyncio
import os
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
    """Assert that we're running in a test environment.

    Raises:
        MockTestEnvironmentError: If not in test environment.
    """
    app_env = os.getenv("APP_ENVIRONMENT", "").lower()
    if app_env != "test":
        raise MockTestEnvironmentError(
            f"Mock objects can only be used in test environment. "
            f"Current APP_ENVIRONMENT: '{app_env}'. "
            f"Set APP_ENVIRONMENT=test to use mocks."
        )


class MockEventEnvelope:
    """Mock event envelope for testing.

    Raises:
        MockTestEnvironmentError: If instantiated outside test environment.
    """

    def __init__(self, event_type: str, global_nonce: int, data: dict | None = None):
        _assert_test_environment()
        self.event = MagicMock()
        self.event.event_type = event_type
        self.event.to_dict.return_value = data or {"id": f"test-{global_nonce}"}
        self.metadata = MagicMock()
        self.metadata.global_nonce = global_nonce


class MockEventStoreClient:
    """Mock event store client for testing.

    Raises:
        MockTestEnvironmentError: If instantiated outside test environment.
    """

    def __init__(self):
        _assert_test_environment()
        self.events: list[MockEventEnvelope] = []
        self._connected = False

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def read_all(
        self,
        from_global_nonce: int = 0,
        max_count: int = 100,
        forward: bool = True,
    ) -> tuple[list[MockEventEnvelope], bool, int]:
        """Return events from the given position with pagination.

        Returns:
            Tuple of (events, is_end, next_from_global_nonce)
        """
        if forward:
            filtered = [e for e in self.events if e.metadata.global_nonce >= from_global_nonce]
            filtered.sort(key=lambda e: e.metadata.global_nonce)
        else:
            filtered = [e for e in self.events if e.metadata.global_nonce <= from_global_nonce]
            filtered.sort(key=lambda e: e.metadata.global_nonce, reverse=True)

        page = filtered[:max_count]
        is_end = len(page) < max_count or len(filtered) <= max_count

        if page:
            if forward:
                next_from = page[-1].metadata.global_nonce + 1
            else:
                next_from = page[-1].metadata.global_nonce - 1
        else:
            next_from = from_global_nonce

        return page, is_end, next_from

    async def read_all_events_from(
        self,
        after_global_nonce: int = 0,
        limit: int = 100,
    ) -> list[MockEventEnvelope]:
        """Return events after the given position (deprecated)."""
        events, _, _ = await self.read_all(
            from_global_nonce=after_global_nonce + 1,
            max_count=limit,
            forward=True,
        )
        return events

    async def subscribe(self, from_global_nonce: int = 0):
        """Yield events starting from the given position."""
        for event in self.events:
            if event.metadata.global_nonce >= from_global_nonce:
                yield event
        # After initial events, wait indefinitely (for live subscription)
        while True:
            await asyncio.sleep(0.1)


class MockProjectionStore:
    """Mock projection store for testing.

    Raises:
        MockTestEnvironmentError: If instantiated outside test environment.
    """

    def __init__(self):
        _assert_test_environment()
        self._positions: dict[str, int] = {}

    async def get_position(self, projection: str) -> int | None:
        return self._positions.get(projection)

    async def set_position(self, projection: str, position: int) -> None:
        self._positions[projection] = position


class MockEventProvenance:
    """Mock event provenance for testing.

    Raises:
        MockTestEnvironmentError: If instantiated outside test environment.
    """

    def __init__(self, event_type: str, stream_id: str = "test-stream", global_nonce: int = 0):
        _assert_test_environment()
        self.event_type = event_type
        self.stream_id = stream_id
        self.global_nonce = global_nonce


class MockProjectionManager:
    """Mock projection manager for testing.

    Raises:
        MockTestEnvironmentError: If instantiated outside test environment.
    """

    def __init__(self):
        _assert_test_environment()
        self.dispatched_events: list[tuple[str, dict]] = []

    async def dispatch_event(self, event_type: str, event_data: dict) -> None:
        self.dispatched_events.append((event_type, event_data))

    async def process_event_envelope(self, envelope: MockEventEnvelope) -> MockEventProvenance:
        """Process an event envelope (mock implementation)."""
        event_type = envelope.event.event_type
        event_data = envelope.event.to_dict()
        self.dispatched_events.append((event_type, event_data))
        return MockEventProvenance(
            event_type=event_type,
            stream_id=f"test-{envelope.metadata.global_nonce}",
            global_nonce=envelope.metadata.global_nonce,
        )


@pytest.fixture
def event_store() -> MockEventStoreClient:
    """Create mock event store."""
    return MockEventStoreClient()


@pytest.fixture
def projection_store() -> MockProjectionStore:
    """Create mock projection store."""
    return MockProjectionStore()


@pytest.fixture
def projection_manager() -> MockProjectionManager:
    """Create mock projection manager."""
    return MockProjectionManager()


@pytest.fixture
def subscription_service(
    event_store: MockEventStoreClient,
    projection_manager: MockProjectionManager,
    projection_store: MockProjectionStore,
) -> EventSubscriptionService:
    """Create subscription service with mocks."""
    return EventSubscriptionService(
        event_store_client=event_store,  # type: ignore
        projection_manager=projection_manager,  # type: ignore
        projection_store=projection_store,  # type: ignore
        batch_size=10,
        position_save_interval=1,
    )


@pytest.mark.unit
class TestEventSubscriptionService:
    """Tests for EventSubscriptionService."""

    @pytest.mark.asyncio
    async def test_start_and_stop(
        self,
        subscription_service: EventSubscriptionService,
    ):
        """Test basic start and stop lifecycle."""
        assert not subscription_service.is_running

        await subscription_service.start()
        assert subscription_service.is_running

        # Give it a moment to start the loop
        await asyncio.sleep(0.1)

        await subscription_service.stop()
        assert not subscription_service.is_running

    @pytest.mark.asyncio
    async def test_loads_position_on_start(
        self,
        subscription_service: EventSubscriptionService,
        projection_store: MockProjectionStore,
    ):
        """Test that position is loaded from store on start."""
        # Set initial position
        projection_store._positions[SUBSCRIPTION_POSITION_KEY] = 42

        await subscription_service.start()
        await asyncio.sleep(0.1)

        assert subscription_service.last_position == 42

        await subscription_service.stop()

    @pytest.mark.asyncio
    async def test_starts_from_zero_if_no_position(
        self,
        subscription_service: EventSubscriptionService,
    ):
        """Test that subscription starts from 0 if no saved position."""
        await subscription_service.start()
        await asyncio.sleep(0.1)

        assert subscription_service.last_position == 0

        await subscription_service.stop()

    @pytest.mark.asyncio
    async def test_catchup_processes_historical_events(
        self,
        subscription_service: EventSubscriptionService,
        event_store: MockEventStoreClient,
        projection_manager: MockProjectionManager,
    ):
        """Test that catch-up phase processes historical events."""
        # Add historical events
        event_store.events = [
            MockEventEnvelope("WorkflowTemplateCreated", 1, {"id": "wf-1"}),
            MockEventEnvelope("SessionStarted", 2, {"id": "session-1"}),
            MockEventEnvelope("PhaseCompleted", 3, {"id": "phase-1"}),
        ]

        await subscription_service.start()

        # Wait for catch-up to complete
        for _ in range(50):  # Max 5 seconds
            if subscription_service.is_caught_up:
                break
            await asyncio.sleep(0.1)

        assert subscription_service.is_caught_up
        assert subscription_service.events_processed == 3
        assert len(projection_manager.dispatched_events) == 3

        # Verify event types were dispatched
        event_types = [e[0] for e in projection_manager.dispatched_events]
        assert "WorkflowTemplateCreated" in event_types
        assert "SessionStarted" in event_types
        assert "PhaseCompleted" in event_types

        await subscription_service.stop()

    @pytest.mark.asyncio
    async def test_saves_position_after_catchup(
        self,
        subscription_service: EventSubscriptionService,
        event_store: MockEventStoreClient,
        projection_store: MockProjectionStore,
    ):
        """Test that position is saved after catch-up."""
        event_store.events = [
            MockEventEnvelope("WorkflowTemplateCreated", 1),
            MockEventEnvelope("WorkflowTemplateCreated", 2),
            MockEventEnvelope("WorkflowTemplateCreated", 3),
        ]

        await subscription_service.start()

        # Wait for catch-up
        for _ in range(50):
            if subscription_service.is_caught_up:
                break
            await asyncio.sleep(0.1)

        await subscription_service.stop()

        # Position should be saved
        assert projection_store._positions.get(SUBSCRIPTION_POSITION_KEY) == 3

    @pytest.mark.asyncio
    async def test_resumes_from_saved_position(
        self,
        event_store: MockEventStoreClient,
        projection_manager: MockProjectionManager,
        projection_store: MockProjectionStore,
    ):
        """Test that subscription resumes from saved position."""
        # Set up events
        event_store.events = [
            MockEventEnvelope("Event1", 1),
            MockEventEnvelope("Event2", 2),
            MockEventEnvelope("Event3", 3),
        ]

        # Set saved position at 2 (events 1 and 2 already processed)
        projection_store._positions[SUBSCRIPTION_POSITION_KEY] = 2

        service = EventSubscriptionService(
            event_store_client=event_store,  # type: ignore
            projection_manager=projection_manager,  # type: ignore
            projection_store=projection_store,  # type: ignore
            batch_size=10,
        )

        await service.start()

        # Wait for catch-up
        for _ in range(50):
            if service.is_caught_up:
                break
            await asyncio.sleep(0.1)

        await service.stop()

        # Only event 3 should be processed (since position was 2)
        assert service.events_processed == 1
        assert len(projection_manager.dispatched_events) == 1
        assert projection_manager.dispatched_events[0][0] == "Event3"

    @pytest.mark.asyncio
    async def test_handles_empty_event_store(
        self,
        subscription_service: EventSubscriptionService,
    ):
        """Test handling of empty event store."""
        await subscription_service.start()

        # Wait for catch-up
        for _ in range(50):
            if subscription_service.is_caught_up:
                break
            await asyncio.sleep(0.1)

        assert subscription_service.is_caught_up
        assert subscription_service.events_processed == 0

        await subscription_service.stop()

    @pytest.mark.asyncio
    async def test_properties(
        self,
        subscription_service: EventSubscriptionService,
        event_store: MockEventStoreClient,
    ):
        """Test service properties."""
        assert not subscription_service.is_running
        assert not subscription_service.is_caught_up
        assert subscription_service.last_position == 0
        assert subscription_service.events_processed == 0

        event_store.events = [
            MockEventEnvelope("Test", 1),
        ]

        await subscription_service.start()

        # Wait for processing
        for _ in range(50):
            if subscription_service.is_caught_up:
                break
            await asyncio.sleep(0.1)

        assert subscription_service.is_running
        assert subscription_service.is_caught_up
        assert subscription_service.last_position == 1
        assert subscription_service.events_processed == 1

        await subscription_service.stop()

        assert not subscription_service.is_running
