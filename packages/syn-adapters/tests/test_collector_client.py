"""Tests for CollectorClient.

These tests verify the HTTP client for sending observability events
to the Collector service.
"""

import asyncio
import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from syn_adapters.collector.client import (
    CollectorClient,
    CollectorEvent,
    generate_event_id,
    generate_tool_event_id,
)


class MockTestEnvironmentError(Exception):
    """Raised when tests run outside test environment."""

    pass


def _assert_test_environment() -> None:
    """Assert that we're running in a test environment."""
    app_env = os.getenv("APP_ENVIRONMENT", "").lower()
    if app_env != "test":
        raise MockTestEnvironmentError(
            f"Tests can only run in test environment. "
            f"Current APP_ENVIRONMENT: '{app_env}'. "
            f"Set APP_ENVIRONMENT=test to run tests."
        )


@pytest.fixture(autouse=True)
def check_environment():
    """Ensure tests run in test environment."""
    _assert_test_environment()


@pytest.mark.unit
class TestEventIdGeneration:
    """Tests for deterministic event ID generation."""

    def test_generate_event_id_is_deterministic(self):
        """Same inputs produce same event ID."""
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        id1 = generate_event_id("session-1", "tool_started", ts, "content-hash")
        id2 = generate_event_id("session-1", "tool_started", ts, "content-hash")
        assert id1 == id2

    def test_generate_event_id_different_inputs(self):
        """Different inputs produce different event IDs."""
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        id1 = generate_event_id("session-1", "tool_started", ts, "hash-1")
        id2 = generate_event_id("session-1", "tool_started", ts, "hash-2")
        assert id1 != id2

    def test_generate_event_id_length(self):
        """Event ID is 32 characters."""
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        event_id = generate_event_id("session-1", "test", ts)
        assert len(event_id) == 32

    def test_generate_tool_event_id(self):
        """Tool event ID includes tool name and use ID."""
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        id1 = generate_tool_event_id("session-1", "started", ts, "Read", "toolu_123")
        id2 = generate_tool_event_id("session-1", "started", ts, "Read", "toolu_456")
        assert id1 != id2  # Different tool_use_id

        id3 = generate_tool_event_id("session-1", "started", ts, "Read", "toolu_123")
        assert id1 == id3  # Same inputs


class TestCollectorEvent:
    """Tests for CollectorEvent model."""

    def test_create_event(self):
        """Create a valid collector event."""
        event = CollectorEvent(
            event_id="a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
            event_type="tool_execution_started",
            session_id="session-123",
            timestamp=datetime.now(UTC),
            data={"tool_name": "Read", "tool_use_id": "toolu_abc"},
        )
        assert event.event_type == "tool_execution_started"
        assert event.data["tool_name"] == "Read"

    def test_event_is_frozen(self):
        """CollectorEvent is immutable."""
        from pydantic import ValidationError

        event = CollectorEvent(
            event_id="a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
            event_type="test",
            session_id="session-123",
            timestamp=datetime.now(UTC),
            data={},
        )
        with pytest.raises(ValidationError):  # Frozen model raises ValidationError
            event.event_type = "modified"


class TestCollectorClient:
    """Tests for CollectorClient HTTP operations."""

    @pytest.fixture
    def client(self):
        """Create a CollectorClient instance."""
        return CollectorClient(
            collector_url="http://localhost:8080",
            batch_size=3,  # Small batch for testing
            max_retries=1,
        )

    @pytest.mark.asyncio
    async def test_context_manager(self, client):
        """Test async context manager."""
        async with client as c:
            assert c._client is not None
        assert client._client is None  # Closed after exit

    @pytest.mark.asyncio
    async def test_emit_buffers_events(self, client):
        """Events are buffered until batch size reached."""
        await client.start()

        # Emit 2 events (batch_size=3, so not sent yet)
        event1 = CollectorEvent(
            event_id="id1" + "0" * 28,
            event_type="test",
            session_id="session-1",
            timestamp=datetime.now(UTC),
            data={},
        )
        event2 = CollectorEvent(
            event_id="id2" + "0" * 28,
            event_type="test",
            session_id="session-1",
            timestamp=datetime.now(UTC),
            data={},
        )

        await client.emit(event1)
        await client.emit(event2)

        assert client.buffer_size == 2

        # Mock the HTTP client for flush during close
        # Note: httpx Response.json() and raise_for_status() are sync, so use MagicMock
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "accepted": 2,
            "duplicates": 0,
            "batch_id": "test-batch",
        }
        client._client.post = AsyncMock(return_value=mock_response)

        await client.close()

    @pytest.mark.asyncio
    async def test_send_tool_started(self):
        """Test convenience method for tool_execution_started."""
        client = CollectorClient(
            collector_url="http://localhost:8080",
            batch_size=10,
        )
        with patch.object(client, "emit", new_callable=AsyncMock) as mock_emit:
            await client.send_tool_started(
                session_id="session-123",
                tool_name="Read",
                tool_use_id="toolu_abc",
                tool_input={"file_path": "/src/main.py"},
            )

            mock_emit.assert_called_once()
            event = mock_emit.call_args[0][0]
            assert event.event_type == "tool_execution_started"
            assert event.data["tool_name"] == "Read"
            assert event.data["tool_use_id"] == "toolu_abc"

    @pytest.mark.asyncio
    async def test_send_tool_completed(self):
        """Test convenience method for tool_execution_completed."""
        client = CollectorClient(
            collector_url="http://localhost:8080",
            batch_size=10,
        )
        with patch.object(client, "emit", new_callable=AsyncMock) as mock_emit:
            await client.send_tool_completed(
                session_id="session-123",
                tool_name="Read",
                tool_use_id="toolu_abc",
                duration_ms=150,
                success=True,
            )

            mock_emit.assert_called_once()
            event = mock_emit.call_args[0][0]
            assert event.event_type == "tool_execution_completed"
            assert event.data["duration_ms"] == 150
            assert event.data["success"] is True

    @pytest.mark.asyncio
    async def test_send_tool_blocked(self):
        """Test convenience method for tool_blocked."""
        client = CollectorClient(
            collector_url="http://localhost:8080",
            batch_size=10,
        )
        with patch.object(client, "emit", new_callable=AsyncMock) as mock_emit:
            await client.send_tool_blocked(
                session_id="session-123",
                tool_name="Write",
                tool_use_id="toolu_xyz",
                reason="Path not allowed",
                validator_name="PathValidator",
            )

            mock_emit.assert_called_once()
            event = mock_emit.call_args[0][0]
            assert event.event_type == "tool_blocked"
            assert event.data["reason"] == "Path not allowed"
            assert event.data["validator_name"] == "PathValidator"

    @pytest.mark.asyncio
    async def test_flush_sends_batch(self):
        """Test flush sends buffered events."""
        client = CollectorClient(
            collector_url="http://localhost:8080",
            batch_size=10,
        )
        await client.start()

        # Add events to buffer
        event1 = CollectorEvent(
            event_id="id1" + "0" * 28,
            event_type="test",
            session_id="session-1",
            timestamp=datetime.now(UTC),
            data={},
        )
        await client.emit(event1)
        assert client.buffer_size == 1

        # Mock the HTTP response (sync methods like json(), raise_for_status())
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "accepted": 1,
            "duplicates": 0,
            "batch_id": "test-batch",
        }
        client._client.post = AsyncMock(return_value=mock_response)

        # Flush
        result = await client.flush()

        assert result is not None
        assert result.accepted == 1
        assert client.buffer_size == 0

        await client._client.aclose()

    @pytest.mark.asyncio
    async def test_stats_tracking(self):
        """Test that statistics are tracked."""
        client = CollectorClient(
            collector_url="http://localhost:8080",
            batch_size=3,
        )
        stats = client.stats
        assert stats["events_sent"] == 0
        assert stats["batches_sent"] == 0
        assert stats["retries"] == 0
        assert stats["buffer_size"] == 0


class TestCollectorClientRetry:
    """Tests for retry logic."""

    @pytest.mark.asyncio
    async def test_retry_on_server_error(self):
        """Client retries on 5xx errors."""
        client = CollectorClient(
            collector_url="http://localhost:8080",
            max_retries=2,
        )
        await client.start()

        # First call fails with 500, second succeeds
        call_count = 0

        async def mock_post(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                response = MagicMock()
                response.status_code = 500
                raise httpx.HTTPStatusError("Server error", request=MagicMock(), response=response)
            response = MagicMock()
            response.json.return_value = {
                "accepted": 1,
                "duplicates": 0,
                "batch_id": "test",
            }
            return response

        client._client.post = mock_post

        event = CollectorEvent(
            event_id="id1" + "0" * 28,
            event_type="test",
            session_id="session-1",
            timestamp=datetime.now(UTC),
            data={},
        )
        await client.emit(event)
        result = await client.flush()

        assert call_count == 2  # One retry
        assert result.accepted == 1

    @pytest.mark.asyncio
    async def test_no_retry_on_client_error(self):
        """Client does not retry on 4xx errors."""
        client = CollectorClient(
            collector_url="http://localhost:8080",
            max_retries=3,
        )
        await client.start()

        async def mock_post(*_args, **_kwargs):
            response = MagicMock()
            response.status_code = 400
            raise httpx.HTTPStatusError("Bad request", request=MagicMock(), response=response)

        client._client.post = mock_post

        event = CollectorEvent(
            event_id="id1" + "0" * 28,
            event_type="test",
            session_id="session-1",
            timestamp=datetime.now(UTC),
            data={},
        )
        await client.emit(event)

        with pytest.raises(httpx.HTTPStatusError):
            await client.flush()


class TestCollectorClientIntegration:
    """Integration-style tests for CollectorClient."""

    @pytest.mark.asyncio
    async def test_full_workflow(self):
        """Test complete workflow: start, send events, flush, close."""
        client = CollectorClient(
            collector_url="http://localhost:8080",
            batch_size=10,
        )
        await client.start()

        # Send tool events
        await client.send_tool_started(
            session_id="exec-session-001",
            tool_name="Read",
            tool_use_id="toolu_read_001",
            tool_input={"file_path": "/src/main.py"},
        )

        await asyncio.sleep(0.01)  # Simulate processing

        await client.send_tool_completed(
            session_id="exec-session-001",
            tool_name="Read",
            tool_use_id="toolu_read_001",
            duration_ms=150,
            success=True,
        )

        # Buffer should have 2 events
        assert client.buffer_size == 2

        # Mock the HTTP response for flush
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "accepted": 2,
            "duplicates": 0,
            "batch_id": "test-batch",
        }
        client._client.post = AsyncMock(return_value=mock_response)

        await client.close()

        # After close, buffer should be flushed
        assert client.buffer_size == 0
        assert client.stats["events_sent"] == 2
