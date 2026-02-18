"""Tests for the collector service."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from syn_collector.collector.service import create_app
from syn_collector.collector.store import InMemoryEventStore
from syn_collector.events.types import CollectedEvent, EventBatch, EventType


@pytest.fixture
def test_client() -> TestClient:
    """Create test client with fresh state."""
    event_store = InMemoryEventStore()
    app = create_app(event_store=event_store)
    return TestClient(app)


@pytest.fixture
def sample_event() -> CollectedEvent:
    """Create a sample event for testing."""
    return CollectedEvent(
        event_id="abc123def456789012345678901234",
        event_type=EventType.SESSION_STARTED,
        session_id="session-123",
        timestamp=datetime.now(UTC),
        data={"start_type": "new"},
    )


@pytest.mark.unit
class TestHealthEndpoint:
    """Tests for health endpoint."""

    def test_health_returns_healthy(self, test_client: TestClient) -> None:
        """Health endpoint should return healthy status."""
        response = test_client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}


class TestEventsEndpoint:
    """Tests for events endpoint."""

    def test_accept_single_event(
        self, test_client: TestClient, sample_event: CollectedEvent
    ) -> None:
        """Single event should be accepted."""
        batch = EventBatch(
            agent_id="agent-001",
            batch_id="batch-001",
            events=[sample_event],
        )

        response = test_client.post("/events", json=batch.model_dump(mode="json"))

        assert response.status_code == 200
        data = response.json()
        assert data["accepted"] == 1
        assert data["duplicates"] == 0
        assert data["batch_id"] == "batch-001"

    def test_reject_duplicate_events(
        self, test_client: TestClient, sample_event: CollectedEvent
    ) -> None:
        """Duplicate events should be rejected."""
        batch = EventBatch(
            agent_id="agent-001",
            batch_id="batch-001",
            events=[sample_event],
        )

        # Send first time
        test_client.post("/events", json=batch.model_dump(mode="json"))

        # Send again with same event
        batch.batch_id = "batch-002"  # type: ignore
        response = test_client.post("/events", json=batch.model_dump(mode="json"))

        assert response.status_code == 200
        data = response.json()
        assert data["accepted"] == 0
        assert data["duplicates"] == 1

    def test_accept_multiple_events(self, test_client: TestClient) -> None:
        """Multiple events should be processed."""
        events = [
            CollectedEvent(
                event_id=f"event-{i:032d}",
                event_type=EventType.TOOL_EXECUTION_STARTED,
                session_id="session-123",
                timestamp=datetime.now(UTC),
                data={"tool_name": f"Tool{i}"},
            )
            for i in range(5)
        ]

        batch = EventBatch(
            agent_id="agent-001",
            batch_id="batch-001",
            events=events,
        )

        response = test_client.post("/events", json=batch.model_dump(mode="json"))

        assert response.status_code == 200
        data = response.json()
        assert data["accepted"] == 5
        assert data["duplicates"] == 0

    def test_empty_batch(self, test_client: TestClient) -> None:
        """Empty batch should be accepted."""
        batch = EventBatch(
            agent_id="agent-001",
            batch_id="batch-001",
            events=[],
        )

        response = test_client.post("/events", json=batch.model_dump(mode="json"))

        assert response.status_code == 200
        data = response.json()
        assert data["accepted"] == 0
        assert data["duplicates"] == 0


class TestStatsEndpoint:
    """Tests for stats endpoint."""

    def test_stats_returns_dedup_info(
        self, test_client: TestClient, sample_event: CollectedEvent
    ) -> None:
        """Stats should include deduplication info."""
        # Send some events
        batch = EventBatch(
            agent_id="agent-001",
            batch_id="batch-001",
            events=[sample_event],
        )
        test_client.post("/events", json=batch.model_dump(mode="json"))

        response = test_client.get("/stats")

        assert response.status_code == 200
        data = response.json()
        assert "dedup" in data
        assert "hit_rate" in data


class TestResetEndpoint:
    """Tests for reset endpoint."""

    def test_reset_clears_state(
        self, test_client: TestClient, sample_event: CollectedEvent
    ) -> None:
        """Reset should clear deduplication state."""
        batch = EventBatch(
            agent_id="agent-001",
            batch_id="batch-001",
            events=[sample_event],
        )

        # Send event
        test_client.post("/events", json=batch.model_dump(mode="json"))

        # Reset
        test_client.post("/reset")

        # Same event should be accepted again
        batch.batch_id = "batch-002"  # type: ignore
        response = test_client.post("/events", json=batch.model_dump(mode="json"))

        assert response.status_code == 200
        data = response.json()
        assert data["accepted"] == 1
        assert data["duplicates"] == 0
