"""#2265: test mode and production deliver events to read models one way.

Production delivers through the coordinator (ADR-055); test and offline runs
through ``ProjectionManager.process_event_envelope``. They used to route by two
mechanisms that disagreed on event names (legacy ``WorkflowCreated``) and on
payloads (realtime's typed ``ExecutionCancelledPayload``). These tests pin that
the in-process path reaches exactly the handlers the coordinator reaches, with
the payload the coordinator builds.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from event_sourcing import CheckpointedProjection, EventEnvelope, EventMetadata

from syn_adapters.projections.manager import ProjectionManager
from syn_adapters.projections.realtime import ExecutionCancelledPayload
from syn_adapters.subscriptions.coordinator_service import create_coordinator_service
from syn_adapters.subscriptions.read_model_dispatch import as_checkpointed
from syn_domain.contexts.orchestration.domain.events.ExecutionCancelledEvent import (
    ExecutionCancelledEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateCreatedEvent import (
    WorkflowTemplateCreatedEvent,
)


def _routing(projection: CheckpointedProjection) -> tuple[type, frozenset[str] | None]:
    subscribed = projection.get_subscribed_event_types()
    return type(projection), None if subscribed is None else frozenset(subscribed)


def _coordinator_routing(
    manager: ProjectionManager,
) -> dict[str, tuple[type, frozenset[str] | None]]:
    service = create_coordinator_service(
        event_store=MagicMock(),
        projection_store=manager.store,
        realtime_projection=manager.realtime,  # type: ignore[arg-type]
        checkpoint_store=MagicMock(),
    )
    registered = [*service._projections, as_checkpointed(manager.realtime)]
    return {p.get_name(): _routing(p) for p in registered if p is not None}


@pytest.mark.unit
def test_test_mode_delivers_to_every_read_model_as_the_coordinator_does() -> None:
    """Every read model the manager feeds is fed in the form the coordinator registers.

    Same adapter class and same subscribed event types means ``handle_event``
    picks the same method and builds the same payload in both modes.
    """
    manager = ProjectionManager()
    manager._ensure_initialized()
    production = _coordinator_routing(manager)

    in_process = [as_checkpointed(p) for p in manager._projections.values()]
    delivered = {p.get_name(): _routing(p) for p in in_process if p is not None}

    assert delivered, "test mode delivers to no read model at all"
    mismatched = {
        name: (routing, production.get(name))
        for name, routing in delivered.items()
        if production.get(name) != routing
    }
    assert not mismatched, f"test mode routes these unlike production: {mismatched}"


def _envelope(event: object, event_type: str) -> EventEnvelope:
    return EventEnvelope(
        event=event,  # type: ignore[arg-type]
        metadata=EventMetadata(
            event_type=event_type,
            aggregate_id="agg-2265",
            aggregate_type="Test",
            aggregate_nonce=1,
            global_nonce=1,
        ),
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execution_cancelled_reaches_realtime_typed_in_test_mode() -> None:
    """The old map's one allow-listed gap: realtime's typed cancel handler."""
    manager = ProjectionManager()
    spy = AsyncMock()
    manager.realtime.on_execution_cancelled = spy  # type: ignore[attr-defined]

    event = ExecutionCancelledEvent(
        workflow_id="wf-2265",
        execution_id="exec-2265",
        phase_id="phase-1",
        cancelled_at=datetime(2026, 11, 12, tzinfo=UTC),
        reason="operator",
    )
    await manager.process_event_envelope(_envelope(event, "ExecutionCancelled"))

    spy.assert_awaited_once()
    (payload,) = spy.await_args.args
    assert isinstance(payload, ExecutionCancelledPayload)
    assert payload.execution_id == "exec-2265"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_legacy_workflow_created_reaches_the_workflow_read_models() -> None:
    """Stored before the rename, still applied by the aggregate: read in both modes.

    Production subscribes by ``on_*`` name, so the alias is what puts the
    legacy type in the coordinator's subscription; test mode uses the same.
    """
    manager = ProjectionManager()
    for name in ("workflow_list", "workflow_detail", "dashboard_metrics"):
        projection = as_checkpointed(manager.get_projection(name))
        assert projection is not None
        subscribed = projection.get_subscribed_event_types()
        assert subscribed is not None and "WorkflowCreated" in subscribed, name

    event = WorkflowTemplateCreatedEvent(
        workflow_id="wf-legacy-2265",
        name="Legacy workflow",
        workflow_type="custom",
        classification="standard",
        repository_url="https://github.com/o/r",
        repository_ref="main",
        phases=[],
    )
    await manager.process_event_envelope(_envelope(event, "WorkflowCreated"))

    listed = await manager.workflow_list.get_all()
    assert [w.id for w in listed] == ["wf-legacy-2265"]
