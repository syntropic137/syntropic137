"""Integration tests for local mode operation.

Tests the full flow: Hook writes → Watcher → Client → Collector → Store
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003 - used at runtime in fixtures

import pytest
from fastapi.testclient import TestClient

from syn_collector.collector.service import create_app
from syn_collector.collector.store import InMemoryObservabilityStore
from syn_collector.watcher.hooks import HookWatcher
from syn_collector.watcher.transcript import TranscriptWatcher


@pytest.mark.unit
class TestLocalModeIntegration:
    """Integration tests for local file-based operation."""

    @pytest.fixture
    def event_store(self) -> InMemoryObservabilityStore:
        """Create shared event store."""
        return InMemoryObservabilityStore()

    @pytest.fixture
    def collector_client(self, event_store: InMemoryObservabilityStore) -> TestClient:
        """Create test client for collector."""
        app = create_app(store=event_store)
        return TestClient(app)

    @pytest.fixture
    def temp_hooks_file(self, tmp_path: Path) -> Path:
        """Create temporary hooks file."""
        return tmp_path / ".agentic" / "analytics" / "events.jsonl"

    @pytest.fixture
    def temp_transcript_dir(self, tmp_path: Path) -> Path:
        """Create temporary transcript directory."""
        transcript_dir = tmp_path / ".claude" / "projects" / "test"
        transcript_dir.mkdir(parents=True)
        return transcript_dir

    @pytest.mark.asyncio
    async def test_hook_event_to_collector_flow(
        self,
        temp_hooks_file: Path,
        collector_client: TestClient,
        event_store: InMemoryObservabilityStore,
    ) -> None:
        """Test flow from hook file write to collector store."""
        # Create hook events file
        temp_hooks_file.parent.mkdir(parents=True, exist_ok=True)

        # Write hook events
        hook_events = [
            {
                "event_type": "session_started",
                "session_id": "test-session-001",
                "timestamp": datetime.now(UTC).isoformat(),
            },
            {
                "event_type": "tool_execution_started",
                "session_id": "test-session-001",
                "tool_name": "Read",
                "tool_use_id": "toolu_test_001",
                "timestamp": datetime.now(UTC).isoformat(),
            },
            {
                "event_type": "tool_execution_completed",
                "session_id": "test-session-001",
                "tool_name": "Read",
                "tool_use_id": "toolu_test_001",
                "success": True,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        ]

        with temp_hooks_file.open("w") as f:
            for event in hook_events:
                f.write(json.dumps(event) + "\n")

        # Read events with watcher
        watcher = HookWatcher(temp_hooks_file)
        collected_events = await watcher.read_existing()

        assert len(collected_events) == 3

        # Send to collector
        from syn_collector.events.types import EventBatch

        batch = EventBatch(
            agent_id="test-agent",
            batch_id="test-batch-001",
            events=collected_events,
        )

        response = collector_client.post("/events", json=batch.model_dump(mode="json"))
        assert response.status_code == 200

        data = response.json()
        assert data["accepted"] == 3
        assert data["duplicates"] == 0

        # Verify events in store
        stored_events = [e for e in event_store.events if e["session_id"] == "test-session-001"]
        assert len(stored_events) == 3

    @pytest.mark.asyncio
    async def test_transcript_token_usage_flow(
        self,
        temp_transcript_dir: Path,
        collector_client: TestClient,
    ) -> None:
        """Test flow from transcript file to token usage events."""
        transcript_file = temp_transcript_dir / "session-123.jsonl"

        # Write transcript messages
        messages = [
            {
                "uuid": "user-001",
                "type": "user",
                "message": {"role": "user", "content": "Hello"},
                "timestamp": datetime.now(UTC).isoformat(),
                "sessionId": "session-123",
            },
            {
                "uuid": "asst-001",
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": "Hi there!",
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                },
                "timestamp": datetime.now(UTC).isoformat(),
                "sessionId": "session-123",
            },
            {
                "uuid": "asst-002",
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "usage": {
                        "input_tokens": 200,
                        "output_tokens": 100,
                        "cache_creation_input_tokens": 50,
                        "cache_read_input_tokens": 150,
                    },
                },
                "timestamp": datetime.now(UTC).isoformat(),
                "sessionId": "session-123",
            },
        ]

        with transcript_file.open("w") as f:
            for msg in messages:
                f.write(json.dumps(msg) + "\n")

        # Read with transcript watcher
        watcher = TranscriptWatcher(transcript_file)
        collected_events = await watcher.read_existing()

        # Only assistant messages with usage should produce events
        assert len(collected_events) == 2

        # Verify token data
        assert collected_events[0].data["input_tokens"] == 100
        assert collected_events[1].data["input_tokens"] == 200

        # Send to collector
        from syn_collector.events.types import EventBatch

        batch = EventBatch(
            agent_id="test-agent",
            batch_id="test-batch-002",
            events=collected_events,
        )

        response = collector_client.post("/events", json=batch.model_dump(mode="json"))
        assert response.status_code == 200

        data = response.json()
        assert data["accepted"] == 2

    @pytest.mark.asyncio
    async def test_deduplication_across_retries(
        self,
        temp_hooks_file: Path,
        collector_client: TestClient,
    ) -> None:
        """Test that retrying sends doesn't create duplicates."""
        temp_hooks_file.parent.mkdir(parents=True, exist_ok=True)

        # Write a single hook event
        event = {
            "event_type": "session_started",
            "session_id": "dedup-test-session",
            "timestamp": "2025-01-01T12:00:00Z",  # Fixed timestamp for determinism
        }

        with temp_hooks_file.open("w") as f:
            f.write(json.dumps(event) + "\n")

        watcher = HookWatcher(temp_hooks_file)
        collected_events = await watcher.read_existing()

        from syn_collector.events.types import EventBatch

        # Send batch first time
        batch1 = EventBatch(
            agent_id="test-agent",
            batch_id="batch-1",
            events=collected_events,
        )
        response1 = collector_client.post("/events", json=batch1.model_dump(mode="json"))
        assert response1.json()["accepted"] == 1

        # "Retry" - send same events again
        batch2 = EventBatch(
            agent_id="test-agent",
            batch_id="batch-2",  # Different batch ID
            events=collected_events,  # Same events
        )
        response2 = collector_client.post("/events", json=batch2.model_dump(mode="json"))

        # Should be rejected as duplicate
        assert response2.json()["accepted"] == 0
        assert response2.json()["duplicates"] == 1

    @pytest.mark.asyncio
    async def test_incremental_file_reading(
        self,
        temp_hooks_file: Path,
    ) -> None:
        """Test that watcher tracks position for incremental reads."""
        temp_hooks_file.parent.mkdir(parents=True, exist_ok=True)

        # Write initial events
        events_batch1 = [
            {
                "event_type": "session_started",
                "session_id": "incremental-test",
                "timestamp": datetime.now(UTC).isoformat(),
            },
        ]

        with temp_hooks_file.open("w") as f:
            for event in events_batch1:
                f.write(json.dumps(event) + "\n")

        watcher = HookWatcher(temp_hooks_file)
        events1 = await watcher.read_existing()
        assert len(events1) == 1

        # Position should be tracked
        position_after_first = watcher.get_position()
        assert position_after_first > 0

        # Append more events
        events_batch2 = [
            {
                "event_type": "tool_execution_started",
                "session_id": "incremental-test",
                "tool_name": "Write",
                "tool_use_id": "toolu_002",
                "timestamp": datetime.now(UTC).isoformat(),
            },
        ]

        with temp_hooks_file.open("a") as f:
            for event in events_batch2:
                f.write(json.dumps(event) + "\n")

        # Read from current position (should only get new events)
        # Note: read_existing resets position, so we use internal method
        watcher._position = position_after_first
        events2 = watcher._read_new_events()

        assert len(events2) == 1
        assert events2[0].data["tool_name"] == "Write"


class TestScaleSimulation:
    """Tests for scale scenarios."""

    @pytest.mark.asyncio
    async def test_concurrent_batches(self) -> None:
        """Test processing multiple batches concurrently."""
        event_store = InMemoryObservabilityStore()
        app = create_app(store=event_store)

        with TestClient(app) as client:
            # Create batches from multiple "agents"
            batches = []
            for agent_id in range(10):
                from syn_collector.events.types import CollectedEvent, EventBatch, EventType

                events = [
                    CollectedEvent(
                        event_id=f"agent{agent_id}-event{i:08d}",
                        event_type=EventType.TOOL_EXECUTION_STARTED,
                        session_id=f"session-agent-{agent_id}",
                        timestamp=datetime.now(UTC),
                        data={"agent": agent_id, "event": i},
                    )
                    for i in range(10)
                ]

                batch = EventBatch(
                    agent_id=f"agent-{agent_id}",
                    batch_id=f"batch-agent-{agent_id}",
                    events=events,
                )
                batches.append(batch)

            # Send all batches
            responses = []
            for batch in batches:
                response = client.post("/events", json=batch.model_dump(mode="json"))
                responses.append(response)

            # Verify all accepted
            total_accepted = sum(r.json()["accepted"] for r in responses)
            total_duplicates = sum(r.json()["duplicates"] for r in responses)

            assert total_accepted == 100  # 10 agents * 10 events each
            assert total_duplicates == 0

            # Verify in store
            assert len(event_store.events) == 100

    @pytest.mark.asyncio
    async def test_deduplication_under_load(self) -> None:
        """Test deduplication with high event volume."""
        event_store = InMemoryObservabilityStore()
        app = create_app(store=event_store, dedup_max_size=1000)

        with TestClient(app) as client:
            from syn_collector.events.types import CollectedEvent, EventBatch, EventType

            # Create events with some duplicates
            unique_events = [
                CollectedEvent(
                    event_id=f"unique-event-{i:08d}",
                    event_type=EventType.TOOL_EXECUTION_STARTED,
                    session_id="load-test-session",
                    timestamp=datetime.now(UTC),
                    data={"index": i},
                )
                for i in range(50)
            ]

            # Send events first time
            batch1 = EventBatch(
                agent_id="load-test",
                batch_id="batch-1",
                events=unique_events,
            )
            response1 = client.post("/events", json=batch1.model_dump(mode="json"))
            assert response1.json()["accepted"] == 50

            # Send mix of new and duplicate events
            mixed_events = unique_events[:25] + [
                CollectedEvent(
                    event_id=f"new-event-{i:08d}",
                    event_type=EventType.TOOL_EXECUTION_COMPLETED,
                    session_id="load-test-session",
                    timestamp=datetime.now(UTC),
                    data={"index": i},
                )
                for i in range(25)
            ]

            batch2 = EventBatch(
                agent_id="load-test",
                batch_id="batch-2",
                events=mixed_events,
            )
            response2 = client.post("/events", json=batch2.model_dump(mode="json"))

            # 25 should be duplicates, 25 should be new
            assert response2.json()["duplicates"] == 25
            assert response2.json()["accepted"] == 25

            # Verify stats endpoint
            stats = client.get("/stats").json()
            assert stats["dedup"]["hits"] > 0

    @pytest.mark.asyncio
    async def test_recovery_after_reset(self) -> None:
        """Test that reset clears state properly."""
        event_store = InMemoryObservabilityStore()
        app = create_app(store=event_store)

        with TestClient(app) as client:
            from syn_collector.events.types import CollectedEvent, EventBatch, EventType

            event = CollectedEvent(
                event_id="reset-test-event-00001234",
                event_type=EventType.SESSION_STARTED,
                session_id="reset-test",
                timestamp=datetime.now(UTC),
                data={},
            )

            batch = EventBatch(
                agent_id="test",
                batch_id="batch-pre-reset",
                events=[event],
            )

            # Send event
            response1 = client.post("/events", json=batch.model_dump(mode="json"))
            assert response1.json()["accepted"] == 1

            # Reset
            reset_response = client.post("/reset")
            assert reset_response.json()["status"] == "reset"

            # Send same event again (should be accepted after reset)
            batch.batch_id = "batch-post-reset"  # type: ignore
            response2 = client.post("/events", json=batch.model_dump(mode="json"))

            # Note: Event store still has the event, but dedup is cleared
            # So the event will be written again (in real system, event store handles idempotency)
            assert response2.json()["accepted"] == 1
