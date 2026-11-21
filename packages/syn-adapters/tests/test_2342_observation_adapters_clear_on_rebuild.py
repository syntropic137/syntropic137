"""#2342: a version rebuild of an observation adapter clears its own data, and only its own.

The coordinator calls ``clear_all_data`` on a version mismatch, then replays.
``ToolTimelineAdapter`` inherited ESP's no-op, so a bump would have replayed
onto the old rows. Each adapter here is built the way the coordinator builds
it (``as_checkpointed``), fed one event through ``handle_event``, and rebuilt
through ``SubscriptionCoordinator._resume_position``.
"""

from __future__ import annotations

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

_TOOL_STARTED = {
    "session_id": "session-1",
    "tool_use_id": "tool-1",
    "tool_name": "Bash",
    "timestamp": "2026-11-21T00:00:00+00:00",
}
_TOKEN_USAGE = {
    "session_id": "session-1",
    "execution_id": "exec-1",
    "observation_type": TOKEN_USAGE,
    "event_type": TOKEN_USAGE,
    "data": {"input_tokens": 100, "output_tokens": 10, "model": "claude-opus-5-5"},
}

#: Every observation read model the coordinator wraps in an
#: ``_ObservationProjectionAdapter``, with its namespace and an event it stores.
_OBSERVATION_READ_MODELS = {
    "tool_timeline": (ToolTimelineProjection, "tool_timelines"),
    "execution_cost": (ExecutionCostProjection, "execution_cost"),
    "session_cost": (SessionCostProjection, "session_cost"),
}


def _envelope(
    event_type: str, data: dict[str, object], nonce: int
) -> EventEnvelope[GenericDomainEvent]:
    return EventEnvelope(
        event=GenericDomainEvent(**data),
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
        for nonce, (event_type, data) in enumerate(
            ((TOOL_EXECUTION_STARTED, _TOOL_STARTED), (TOKEN_USAGE, _TOKEN_USAGE)), start=1
        ):
            if adapter.should_handle_event_type(event_type):
                await adapter.handle_event(_envelope(event_type, data, nonce), checkpoints)
    return adapters


@pytest.mark.asyncio
@pytest.mark.parametrize("rebuilt", sorted(_OBSERVATION_READ_MODELS))
async def test_version_rebuild_clears_only_the_rebuilt_adapters_namespace(rebuilt: str) -> None:
    store = InMemoryProjectionStore()
    adapters = await _fed_adapters(store)
    for _projection_type, namespace in _OBSERVATION_READ_MODELS.values():
        assert await store.get_all(namespace), f"{namespace} stored nothing to clear"

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
            assert stored, f"rebuilding {rebuilt} deleted {namespace}"
