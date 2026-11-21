"""#2342: a version rebuild of an observation adapter clears its own data, and only its own.

The coordinator calls ``clear_all_data`` on a version mismatch, then replays.
``ToolTimelineAdapter`` inherited ESP's no-op, so a bump would have replayed
onto the old rows. Each adapter here is built the way the coordinator builds
it (``as_checkpointed``), fed one event through ``handle_event``, and rebuilt
through ``SubscriptionCoordinator._resume_position``.
"""

from __future__ import annotations

import copy
import os

# Must be set before any syn_* imports
os.environ.setdefault("APP_ENVIRONMENT", "test")

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from event_sourcing import (
    EventEnvelope,
    EventMetadata,
    GenericDomainEvent,
    MemoryCheckpointStore,
    ProjectionCheckpoint,
    SubscriptionCoordinator,
)

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_adapters.subscriptions.read_model_dispatch import as_checkpointed
from syn_domain.contexts.agent_sessions.slices.session_cost.projection import (
    SessionCostProjection,
)
from syn_domain.contexts.agent_sessions.slices.tool_timeline import ToolTimelineProjection
from syn_domain.contexts.orchestration.slices.execution_cost.projection import (
    ExecutionCostProjection,
)
from syn_shared.events import TOKEN_USAGE, TOOL_EXECUTION_STARTED

if TYPE_CHECKING:
    from event_sourcing import CheckpointedProjection

pytestmark = pytest.mark.unit

#: Two sessions and two executions, so every namespace holds more than one row
#: and a clear that drops one foreign row is as visible as one that drops all.
_EVENTS = [
    (
        TOOL_EXECUTION_STARTED,
        GenericDomainEvent(
            session_id=f"session-{n}",
            tool_use_id=f"tool-{n}",
            tool_name="Bash",
            timestamp="2026-11-21T00:00:00+00:00",
        ),
    )
    for n in (1, 2)
] + [
    (
        TOKEN_USAGE,
        GenericDomainEvent(
            session_id=f"session-{n}",
            execution_id=f"exec-{n}",
            observation_type=TOKEN_USAGE,
            event_type=TOKEN_USAGE,
            data={"input_tokens": 100 * n, "output_tokens": 10, "model": "claude-opus-5-5"},
        ),
    )
    for n in (1, 2)
]

#: Every observation read model the coordinator wraps in an
#: ``_ObservationProjectionAdapter``, with its namespace and an event it stores.
_OBSERVATION_READ_MODELS = {
    "tool_timeline": (ToolTimelineProjection, "tool_timelines"),
    "execution_cost": (ExecutionCostProjection, "execution_cost"),
    "session_cost": (SessionCostProjection, "session_cost"),
}


def _envelope(
    event_type: str, event: GenericDomainEvent, nonce: int
) -> EventEnvelope[GenericDomainEvent]:
    return EventEnvelope(
        event=event,
        metadata=EventMetadata(
            event_type=event_type,
            aggregate_id="session-1",
            aggregate_type="AgentSession",
            aggregate_nonce=nonce,
            global_nonce=nonce,
        ),
    )


async def _fed_adapters(store: InMemoryProjectionStore) -> dict[str, CheckpointedProjection]:
    """Each observation adapter, as registered, after one event has reached its handler."""
    adapters: dict[str, CheckpointedProjection] = {}
    checkpoints = MemoryCheckpointStore()
    for name, (projection_type, _namespace) in _OBSERVATION_READ_MODELS.items():
        adapter = as_checkpointed(projection_type(store))
        assert adapter is not None
        adapters[name] = adapter
        for nonce, (event_type, event) in enumerate(_EVENTS, start=1):
            if adapter.should_handle_event_type(event_type):
                await adapter.handle_event(_envelope(event_type, event, nonce), checkpoints)
    return adapters


@pytest.mark.asyncio
@pytest.mark.parametrize("rebuilt", sorted(_OBSERVATION_READ_MODELS))
async def test_version_rebuild_clears_only_the_rebuilt_adapters_namespace(rebuilt: str) -> None:
    store = InMemoryProjectionStore()
    adapters = await _fed_adapters(store)
    before = {
        namespace: copy.deepcopy(await store.get_all(namespace))
        for _projection_type, namespace in _OBSERVATION_READ_MODELS.values()
    }
    for namespace, rows in before.items():
        assert len(rows) == 2, f"{namespace} stored {len(rows)} rows, expected one per session"

    adapter = adapters[rebuilt]
    checkpoints = MemoryCheckpointStore()
    await checkpoints.save_checkpoint(
        ProjectionCheckpoint(
            projection_name=adapter.get_name(),
            global_position=10,
            updated_at=datetime.now(UTC),
            version=adapter.get_version() - 1,
        )
    )
    coordinator = SubscriptionCoordinator(
        event_store=Mock(), checkpoint_store=checkpoints, projections=[adapter]
    )

    assert await coordinator._resume_position(adapter.get_name(), adapter) == 0

    for name, (_projection_type, namespace) in _OBSERVATION_READ_MODELS.items():
        stored = await store.get_all(namespace)
        if name == rebuilt:
            assert stored == [], f"{namespace} kept its rows through a version rebuild"
        else:
            assert stored == before[namespace], f"rebuilding {rebuilt} changed {namespace}"
