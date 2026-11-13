"""An operation recorded in a session reaches its execution's live stream (#1853).

The realtime projection forwards an event only when its payload carries
``execution_id``. OperationRecorded carried none, so every operation was
dropped before any SSE client saw it, while the projection's own test passed
because it fed the handler a hand-built dict that did have the key.

These tests start from the aggregate instead, push the event through the same
encode/decode the event store does, and read what comes out of the stream.
"""

from __future__ import annotations

import json

import pytest
from event_sourcing import DomainEvent, EventEnvelope, EventMetadata, decode_event
from event_sourcing.core.envelope import encode_payload
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

from syn_adapters.projections.realtime import RealTimeProjection, SSEEventFrame
from syn_adapters.subscriptions.realtime_adapter import RealTimeProjectionAdapter
from syn_domain.contexts.agent_sessions._shared.value_objects import OperationType
from syn_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
    AgentSessionAggregate,
)
from syn_domain.contexts.agent_sessions.domain.commands.RecordOperationCommand import (
    RecordOperationCommand,
)
from syn_domain.contexts.agent_sessions.domain.commands.StartSessionCommand import (
    StartSessionCommand,
)
from syn_domain.contexts.agent_sessions.domain.events.OperationRecordedEvent import (
    OperationRecordedEvent,
)


def _operation_recorded(session_id: str, execution_id: str) -> DomainEvent:
    """The OperationRecorded a running session of ``execution_id`` emits,
    as a reader decodes it back out of the store."""
    session = AgentSessionAggregate()
    session.start_session(
        StartSessionCommand(
            aggregate_id=session_id,
            workflow_id="wf-1853",
            execution_id=execution_id,
            phase_id="phase-1",
            agent_provider="claude",
        )
    )
    session.record_operation(
        RecordOperationCommand(
            aggregate_id=session_id,
            operation_type=OperationType.TOOL_EXECUTION_COMPLETED,
            tool_name="Bash",
            tool_use_id="toolu_1853",
        )
    )
    emitted = [e.event for e in session.get_uncommitted_events()][-1]
    assert isinstance(emitted, OperationRecordedEvent)
    return decode_event("OperationRecorded", 1, encode_payload(emitted)).event


async def _deliver(projection: RealTimeProjection, event: DomainEvent) -> None:
    envelope = EventEnvelope(
        event=event,
        metadata=EventMetadata(
            event_id="evt-1853",
            aggregate_id="sess-1853",
            aggregate_type="AgentSession",
            aggregate_nonce=2,
            global_nonce=7,
            event_type="OperationRecorded",
        ),
    )
    await RealTimeProjectionAdapter(projection).handle_event(envelope, MemoryCheckpointStore())


@pytest.mark.unit
async def test_operation_reaches_its_execution_stream_and_no_other() -> None:
    projection = RealTimeProjection()
    own = await projection.connect("exec-1853-E")
    other = await projection.connect("exec-1853-F")

    await _deliver(projection, _operation_recorded("sess-1853", "exec-1853-E"))

    assert own.qsize() == 1
    frame = own.get_nowait()
    assert isinstance(frame, SSEEventFrame)
    assert frame.event_type == "OperationRecorded"
    assert frame.execution_id == "exec-1853-E"
    data = frame.data
    assert data["session_id"] == "sess-1853"
    assert data["execution_id"] == "exec-1853-E"
    assert data["tool_use_id"] == "toolu_1853"
    assert other.empty()


@pytest.mark.unit
def test_an_operation_stored_before_execution_id_existed_still_loads() -> None:
    """A v2 payload, written with no execution_id key, decodes unchanged."""
    stored = {
        "session_id": "sess-old",
        "operation_id": "op-old",
        "operation_type": "tool_completed",
        "timestamp": "2026-10-01T12:00:00+00:00",
        "tool_name": "Read",
    }

    event = decode_event("OperationRecorded", 1, json.dumps(stored).encode()).event

    assert isinstance(event, OperationRecordedEvent)
    assert event.execution_id is None
    assert event.session_id == "sess-old"
    assert event.tool_name == "Read"
