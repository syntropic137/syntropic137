"""Tests for event bridge module."""

from __future__ import annotations

import json
from pathlib import Path  # noqa: TC003 - used at runtime
from unittest.mock import AsyncMock, MagicMock

import pytest
from agentic_hooks import EventType, HookEvent

from aef_adapters.events import (
    DomainEvent,
    EventBridge,
    HookToDomainTranslator,
    JSONLWatcher,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_hook_event() -> HookEvent:
    """Create a sample hook event for testing."""
    return HookEvent(
        event_type=EventType.SESSION_STARTED,
        session_id="session-123",
        workflow_id="workflow-456",
        phase_id="research",
        data={"source": "test"},
    )


@pytest.fixture
def sample_tool_event() -> HookEvent:
    """Create a sample tool execution event."""
    return HookEvent(
        event_type=EventType.TOOL_EXECUTION_STARTED,
        session_id="session-123",
        data={
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "contents": "print('hello')"},
        },
    )


@pytest.fixture
def jsonl_file(tmp_path: Path) -> Path:
    """Create a temporary JSONL file with test events."""
    file_path = tmp_path / "events.jsonl"

    events = [
        HookEvent(
            event_type=EventType.SESSION_STARTED,
            session_id="session-1",
            event_id="event-1",
            data={"source": "test"},
        ),
        HookEvent(
            event_type=EventType.TOOL_EXECUTION_STARTED,
            session_id="session-1",
            event_id="event-2",
            data={"tool_name": "Write"},
        ),
        HookEvent(
            event_type=EventType.SESSION_COMPLETED,
            session_id="session-1",
            event_id="event-3",
            data={"reason": "done"},
        ),
    ]

    with file_path.open("w") as f:
        for event in events:
            f.write(json.dumps(event.to_dict()) + "\n")

    return file_path


# ============================================================================
# Test HookToDomainTranslator
# ============================================================================


class TestHookToDomainTranslator:
    """Tests for HookToDomainTranslator."""

    def test_translate_session_started(self, sample_hook_event: HookEvent) -> None:
        """Test translating SESSION_STARTED event."""
        translator = HookToDomainTranslator()
        domain_event = translator.translate(sample_hook_event)

        assert domain_event.event_type == "SessionStarted"
        assert domain_event.aggregate_type == "Session"
        assert domain_event.aggregate_id == "session-123"
        assert domain_event.event_data["session_id"] == "session-123"
        assert domain_event.event_data["workflow_id"] == "workflow-456"
        assert domain_event.event_data["phase_id"] == "research"

    def test_translate_tool_execution_started(
        self, sample_tool_event: HookEvent
    ) -> None:
        """Test translating TOOL_EXECUTION_STARTED event."""
        translator = HookToDomainTranslator()
        domain_event = translator.translate(sample_tool_event)

        assert domain_event.event_type == "ToolExecutionStarted"
        assert domain_event.event_data["tool_name"] == "Write"
        assert domain_event.event_data["tool_input"]["file_path"] == "test.py"

    def test_translate_tool_execution_completed(self) -> None:
        """Test translating TOOL_EXECUTION_COMPLETED event."""
        hook_event = HookEvent(
            event_type=EventType.TOOL_EXECUTION_COMPLETED,
            session_id="session-123",
            data={
                "tool_name": "Write",
                "tool_output": "File written",
                "duration_ms": 150,
                "success": True,
            },
        )

        translator = HookToDomainTranslator()
        domain_event = translator.translate(hook_event)

        assert domain_event.event_type == "ToolExecutionCompleted"
        assert domain_event.event_data["tool_name"] == "Write"
        assert domain_event.event_data["tool_output"] == "File written"
        assert domain_event.event_data["duration_ms"] == 150
        assert domain_event.event_data["success"] is True

    def test_translate_tool_blocked(self) -> None:
        """Test translating TOOL_BLOCKED event."""
        hook_event = HookEvent(
            event_type=EventType.TOOL_BLOCKED,
            session_id="session-123",
            data={
                "tool_name": "Bash",
                "tool_input": {"command": "rm -rf /"},
                "reason": "Dangerous command detected",
                "validator": "security.bash",
            },
        )

        translator = HookToDomainTranslator()
        domain_event = translator.translate(hook_event)

        assert domain_event.event_type == "ToolBlocked"
        assert domain_event.event_data["tool_name"] == "Bash"
        assert domain_event.event_data["reason"] == "Dangerous command detected"
        assert domain_event.event_data["validator"] == "security.bash"

    def test_translate_agent_request_started(self) -> None:
        """Test translating AGENT_REQUEST_STARTED event."""
        hook_event = HookEvent(
            event_type=EventType.AGENT_REQUEST_STARTED,
            session_id="session-123",
            data={
                "model": "claude-sonnet-4-20250514",
                "message_count": 3,
                "max_tokens": 4096,
                "temperature": 0.7,
            },
        )

        translator = HookToDomainTranslator()
        domain_event = translator.translate(hook_event)

        assert domain_event.event_type == "AgentRequestStarted"
        assert domain_event.event_data["model"] == "claude-sonnet-4-20250514"
        assert domain_event.event_data["message_count"] == 3

    def test_translate_agent_request_completed(self) -> None:
        """Test translating AGENT_REQUEST_COMPLETED event."""
        hook_event = HookEvent(
            event_type=EventType.AGENT_REQUEST_COMPLETED,
            session_id="session-123",
            data={
                "model": "claude-sonnet-4-20250514",
                "input_tokens": 1000,
                "output_tokens": 500,
                "total_tokens": 1500,
                "duration_seconds": 2.5,
            },
        )

        translator = HookToDomainTranslator()
        domain_event = translator.translate(hook_event)

        assert domain_event.event_type == "AgentRequestCompleted"
        assert domain_event.event_data["total_tokens"] == 1500
        assert domain_event.event_data["duration_seconds"] == 2.5

    def test_translate_custom_event(self) -> None:
        """Test translating custom event type."""
        hook_event = HookEvent(
            event_type="my_custom_event",
            session_id="session-123",
            data={"custom_field": "custom_value"},
        )

        translator = HookToDomainTranslator()
        domain_event = translator.translate(hook_event)

        assert domain_event.event_type == "CustomEvent"
        assert domain_event.event_data["custom_field"] == "custom_value"

    def test_translate_preserves_event_id(self, sample_hook_event: HookEvent) -> None:
        """Test that translation preserves original event ID."""
        translator = HookToDomainTranslator()
        domain_event = translator.translate(sample_hook_event)

        assert domain_event.event_id == sample_hook_event.event_id

    def test_translate_preserves_timestamp(self, sample_hook_event: HookEvent) -> None:
        """Test that translation preserves original timestamp."""
        translator = HookToDomainTranslator()
        domain_event = translator.translate(sample_hook_event)

        assert domain_event.created_at == sample_hook_event.timestamp

    def test_translate_includes_metadata(self, sample_hook_event: HookEvent) -> None:
        """Test that translation includes source metadata."""
        translator = HookToDomainTranslator()
        domain_event = translator.translate(sample_hook_event)

        assert domain_event.metadata["source"] == "hook_event"
        assert domain_event.metadata["original_event_id"] == sample_hook_event.event_id
        assert domain_event.metadata["original_event_type"] == "session_started"

    def test_translate_with_raw_event(self, sample_hook_event: HookEvent) -> None:
        """Test that raw event can be included in metadata."""
        translator = HookToDomainTranslator(include_raw_event=True)
        domain_event = translator.translate(sample_hook_event)

        assert "raw_event" in domain_event.metadata
        assert domain_event.metadata["raw_event"]["event_type"] == "session_started"

    def test_translate_batch(self) -> None:
        """Test batch translation of events."""
        events = [
            HookEvent(
                event_type=EventType.SESSION_STARTED,
                session_id="s1",
            ),
            HookEvent(
                event_type=EventType.TOOL_EXECUTION_STARTED,
                session_id="s1",
                data={"tool_name": "Test"},
            ),
        ]

        translator = HookToDomainTranslator()
        domain_events = translator.translate_batch(events)

        assert len(domain_events) == 2
        assert domain_events[0].event_type == "SessionStarted"
        assert domain_events[1].event_type == "ToolExecutionStarted"


# ============================================================================
# Test JSONLWatcher
# ============================================================================


class TestJSONLWatcher:
    """Tests for JSONLWatcher."""

    @pytest.mark.asyncio
    async def test_read_all_events(self, jsonl_file: Path) -> None:
        """Test reading all events from file."""
        watcher = JSONLWatcher(jsonl_file)
        events = await watcher.read_all()

        assert len(events) == 3
        assert events[0].event_type == EventType.SESSION_STARTED
        assert events[1].event_type == EventType.TOOL_EXECUTION_STARTED
        assert events[2].event_type == EventType.SESSION_COMPLETED

    @pytest.mark.asyncio
    async def test_read_all_empty_file(self, tmp_path: Path) -> None:
        """Test reading from empty file."""
        file_path = tmp_path / "empty.jsonl"
        file_path.touch()

        watcher = JSONLWatcher(file_path)
        events = await watcher.read_all()

        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_read_all_nonexistent_file(self, tmp_path: Path) -> None:
        """Test reading from nonexistent file."""
        file_path = tmp_path / "nonexistent.jsonl"

        watcher = JSONLWatcher(file_path)
        events = await watcher.read_all()

        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_read_from_position(self, jsonl_file: Path) -> None:
        """Test reading from a specific position."""
        watcher = JSONLWatcher(jsonl_file)

        # Read first event
        events1, pos1 = await watcher.read_from(0)

        # Read remaining from position
        watcher2 = JSONLWatcher(jsonl_file)
        events2, pos2 = await watcher2.read_from(pos1)

        # We should have read the first 3 events, then 0 more
        # (since pos1 is at the end after reading all)
        assert len(events1) == 3
        assert len(events2) == 0
        assert pos2 == pos1

    @pytest.mark.asyncio
    async def test_position_tracking(self, jsonl_file: Path) -> None:
        """Test that position is updated after reading."""
        watcher = JSONLWatcher(jsonl_file)

        assert watcher.get_position() == 0

        await watcher.read_all()

        assert watcher.get_position() > 0

    @pytest.mark.asyncio
    async def test_reset_position(self, jsonl_file: Path) -> None:
        """Test resetting position."""
        watcher = JSONLWatcher(jsonl_file)
        await watcher.read_all()

        watcher.reset_position()

        assert watcher.get_position() == 0

    @pytest.mark.asyncio
    async def test_handles_invalid_json(self, tmp_path: Path) -> None:
        """Test that invalid JSON lines are skipped."""
        file_path = tmp_path / "mixed.jsonl"
        with file_path.open("w") as f:
            f.write(json.dumps(HookEvent(
                event_type=EventType.SESSION_STARTED,
                session_id="s1",
            ).to_dict()) + "\n")
            f.write("invalid json line\n")
            f.write(json.dumps(HookEvent(
                event_type=EventType.SESSION_COMPLETED,
                session_id="s1",
            ).to_dict()) + "\n")

        watcher = JSONLWatcher(file_path)
        events = await watcher.read_all()

        # Should skip the invalid line
        assert len(events) == 2


# ============================================================================
# Test EventBridge
# ============================================================================


class TestEventBridge:
    """Tests for EventBridge."""

    @pytest.fixture
    def mock_event_store(self) -> MagicMock:
        """Create a mock event store."""
        store = MagicMock()
        store.append = AsyncMock(return_value="stored-event-id")
        return store

    @pytest.mark.asyncio
    async def test_process_file(
        self,
        jsonl_file: Path,
        mock_event_store: MagicMock,
    ) -> None:
        """Test processing events from file."""
        bridge = EventBridge(mock_event_store)

        count, position = await bridge.process_file(jsonl_file)

        assert count == 3
        assert position > 0
        assert mock_event_store.append.call_count == 3

    @pytest.mark.asyncio
    async def test_process_file_with_callback(
        self,
        jsonl_file: Path,
    ) -> None:
        """Test processing events with callback."""
        received_events: list[DomainEvent] = []

        def callback(event: DomainEvent) -> None:
            received_events.append(event)

        bridge = EventBridge()
        count, _ = await bridge.process_file(jsonl_file, callback=callback)

        assert count == 3
        assert len(received_events) == 3

    @pytest.mark.asyncio
    async def test_process_file_without_store(
        self,
        jsonl_file: Path,
    ) -> None:
        """Test processing without event store (translate only)."""
        bridge = EventBridge()  # No event store

        count, _ = await bridge.process_file(jsonl_file)

        assert count == 3

    @pytest.mark.asyncio
    async def test_position_tracking(
        self,
        jsonl_file: Path,
    ) -> None:
        """Test that bridge tracks file position."""
        bridge = EventBridge()

        await bridge.process_file(jsonl_file)
        position = bridge.get_position(jsonl_file)

        assert position > 0

        # Processing again should yield no new events
        count, _ = await bridge.process_file(jsonl_file)
        assert count == 0

    @pytest.mark.asyncio
    async def test_set_position(
        self,
        jsonl_file: Path,
    ) -> None:
        """Test setting position for resuming."""
        bridge = EventBridge()

        # Process and get position
        await bridge.process_file(jsonl_file)
        position = bridge.get_position(jsonl_file)

        # Create new bridge and set position
        bridge2 = EventBridge()
        bridge2.set_position(jsonl_file, position)

        # Should have no new events
        count, _ = await bridge2.process_file(jsonl_file)
        assert count == 0

    def test_translate_directly(self) -> None:
        """Test translating event directly."""
        bridge = EventBridge()
        hook_event = HookEvent(
            event_type=EventType.SESSION_STARTED,
            session_id="session-123",
        )

        domain_event = bridge.translate(hook_event)

        assert domain_event.event_type == "SessionStarted"


# ============================================================================
# Test DomainEvent
# ============================================================================


class TestDomainEvent:
    """Tests for DomainEvent dataclass."""

    def test_create_domain_event(self) -> None:
        """Test creating a domain event."""
        event = DomainEvent(
            event_type="SessionStarted",
            aggregate_type="Session",
            aggregate_id="session-123",
            event_data={"started_at": "2025-01-01T00:00:00Z"},
        )

        assert event.event_type == "SessionStarted"
        assert event.aggregate_type == "Session"
        assert event.aggregate_id == "session-123"
        assert event.version == 1  # Default

    def test_domain_event_to_dict(self) -> None:
        """Test converting domain event to dictionary."""
        event = DomainEvent(
            event_type="SessionStarted",
            aggregate_type="Session",
            aggregate_id="session-123",
            event_data={"started_at": "2025-01-01T00:00:00Z"},
            metadata={"source": "test"},
        )

        data = event.to_dict()

        assert data["event_type"] == "SessionStarted"
        assert data["aggregate_type"] == "Session"
        assert data["aggregate_id"] == "session-123"
        assert data["metadata"]["source"] == "test"
        assert "event_id" in data
        assert "created_at" in data
