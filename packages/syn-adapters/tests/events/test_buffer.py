"""Tests for EventBuffer."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_adapters.events.buffer import EventBuffer, parse_jsonl_events


@pytest.mark.unit
class TestEventBuffer:
    """Tests for EventBuffer class."""

    @pytest.fixture
    def mock_store(self) -> MagicMock:
        """Create a mock AgentEventStore."""
        store = MagicMock()
        store.insert_batch = AsyncMock(return_value=0)
        return store

    @pytest.mark.asyncio
    async def test_add_event(self, mock_store: MagicMock) -> None:
        """Should add event to buffer."""
        buffer = EventBuffer(mock_store, flush_size=10)
        await buffer.add({"event_type": "test", "session_id": "sess-1"})
        assert buffer.size == 1

    @pytest.mark.asyncio
    async def test_flush_on_size(self, mock_store: MagicMock) -> None:
        """Should flush when reaching flush_size."""
        mock_store.insert_batch.return_value = 3
        buffer = EventBuffer(mock_store, flush_size=3)

        await buffer.add({"event_type": "test1", "session_id": "sess-1"})
        await buffer.add({"event_type": "test2", "session_id": "sess-1"})
        assert mock_store.insert_batch.call_count == 0

        await buffer.add({"event_type": "test3", "session_id": "sess-1"})
        assert mock_store.insert_batch.call_count == 1
        assert buffer.size == 0

    @pytest.mark.asyncio
    async def test_manual_flush(self, mock_store: MagicMock) -> None:
        """Should flush on manual call."""
        mock_store.insert_batch.return_value = 2
        buffer = EventBuffer(mock_store, flush_size=100)

        await buffer.add({"event_type": "test1", "session_id": "sess-1"})
        await buffer.add({"event_type": "test2", "session_id": "sess-1"})

        count = await buffer.flush()
        assert count == 2
        assert buffer.size == 0

    @pytest.mark.asyncio
    async def test_add_many(self, mock_store: MagicMock) -> None:
        """Should add multiple events at once."""
        buffer = EventBuffer(mock_store, flush_size=100)

        events = [{"event_type": f"test{i}", "session_id": "sess-1"} for i in range(10)]
        await buffer.add_many(events)

        assert buffer.size == 10

    @pytest.mark.asyncio
    async def test_add_with_context(self, mock_store: MagicMock) -> None:
        """Should add execution context to events."""
        mock_store.insert_batch.return_value = 1
        buffer = EventBuffer(mock_store, flush_size=1)

        await buffer.add(
            {"event_type": "test", "session_id": "sess-1"},
            execution_id="exec-123",
            phase_id="phase-456",
        )

        # Check the event passed to insert_batch
        call_args = mock_store.insert_batch.call_args[0][0]
        assert call_args[0]["execution_id"] == "exec-123"
        assert call_args[0]["phase_id"] == "phase-456"

    @pytest.mark.asyncio
    async def test_stop_flushes_remaining(self, mock_store: MagicMock) -> None:
        """Should flush remaining events on stop."""
        mock_store.insert_batch.return_value = 2
        buffer = EventBuffer(mock_store, flush_size=100)

        await buffer.add({"event_type": "test1", "session_id": "sess-1"})
        await buffer.add({"event_type": "test2", "session_id": "sess-1"})

        await buffer.stop()

        assert mock_store.insert_batch.call_count == 1
        assert buffer.size == 0

    @pytest.mark.asyncio
    async def test_metrics(self, mock_store: MagicMock) -> None:
        """Should track metrics."""
        mock_store.insert_batch.return_value = 5
        buffer = EventBuffer(mock_store, flush_size=5)

        for i in range(10):
            await buffer.add({"event_type": f"test{i}", "session_id": "sess-1"})

        assert buffer.total_events == 10
        assert buffer.total_flushes == 2


class TestParseJsonlEvents:
    """Tests for parse_jsonl_events function."""

    def test_parse_valid_events(self) -> None:
        """Should parse valid JSONL events."""
        stdout = """{"type": "started", "timestamp": "2025-01-01T00:00:00Z"}
{"type": "tool_use", "tool": "Bash", "input": {"command": "ls"}}
{"event_type": "completed", "success": true}"""

        events = parse_jsonl_events(stdout)

        assert len(events) == 3
        assert events[0]["event_type"] == "started"
        assert events[1]["event_type"] == "tool_use"
        assert events[2]["event_type"] == "completed"

    def test_skip_invalid_json(self) -> None:
        """Should skip invalid JSON lines."""
        stdout = """{"type": "started"}
not json
{"type": "completed"}"""

        events = parse_jsonl_events(stdout)

        assert len(events) == 2

    def test_skip_non_event_json(self) -> None:
        """Should skip JSON without type/event_type."""
        stdout = """{"type": "started"}
{"foo": "bar"}
{"other": 123}"""

        events = parse_jsonl_events(stdout)

        assert len(events) == 1

    def test_empty_input(self) -> None:
        """Should handle empty input."""
        events = parse_jsonl_events("")
        assert events == []

    def test_normalize_type_to_event_type(self) -> None:
        """Should normalize 'type' to 'event_type'."""
        stdout = '{"type": "started"}'

        events = parse_jsonl_events(stdout)

        assert len(events) == 1
        assert "event_type" in events[0]
        assert "type" not in events[0]
