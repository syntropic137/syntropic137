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
from event_sourcing import EventEnvelope, EventMetadata, SubscriptionCoordinator
from event_sourcing.core.event import GenericDomainEvent

from syn_adapters.projections.manager import ProjectionManager
from syn_adapters.projections.realtime import ExecutionCancelledPayload, RealTimeProjection
from syn_adapters.subscriptions.coordinator_service import create_coordinator_service
from syn_adapters.subscriptions.realtime_adapter import RealTimeProjectionAdapter
from syn_domain.contexts.orchestration.domain.events.ExecutionCancelledEvent import (
    ExecutionCancelledEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateCreatedEvent import (
    WorkflowTemplateCreatedEvent,
)


class _NoCheckpoints:
    async def get_checkpoint(self, projection_name: str) -> None:
        return None

    async def save_checkpoint(self, checkpoint: object) -> None:
        pass

    async def delete_checkpoint(self, projection_name: str) -> None:
        pass

    async def get_all_checkpoints(self) -> list[object]:
        return []


def _target(projection: object) -> object:
    """The read model behind a coordinator adapter, or the projection itself."""
    return getattr(projection, "_projection", getattr(projection, "_realtime", projection))


Call = tuple[str, str, object]


def _spy_on_handlers(targets: list[object], calls: list[Call]) -> None:
    """Replace every ``on_*`` handler on each instance with a recorder."""
    for target in targets:
        for method in dir(type(target)):
            if not method.startswith("on_") or not callable(getattr(target, method)):
                continue

            async def record(payload: object, owner: str = type(target).__name__, m: str = method):
                calls.append((owner, m, payload))

            setattr(target, method, record)


def _event(nonce: int, event_type: str) -> EventEnvelope:
    event = GenericDomainEvent(
        workflow_id="wf-2265",
        execution_id="exec-2265",
        phase_id="phase-1",
        cancelled_at=datetime(2026, 11, 12, tzinfo=UTC),
        reason="parity",
        nested={"when": datetime(2026, 11, 12, tzinfo=UTC)},
        items=["first", "second"],
    )
    return EventEnvelope(
        event=event,
        metadata=EventMetadata(
            event_type=event_type,
            aggregate_id="agg-2265",
            aggregate_type="Test",
            aggregate_nonce=nonce,
            global_nonce=nonce,
        ),
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_test_mode_calls_the_handlers_the_coordinator_calls_with_equal_payloads() -> None:
    """For every event a read model handles, both paths call the same methods alike.

    Test mode is ``ProjectionManager.process_event_envelope``; production is
    ``SubscriptionCoordinator.dispatch_event`` over what
    ``create_coordinator_service`` registers for the same read models. Each
    side gets its own instances with every ``on_*`` handler recorded, and the
    recorded ``(read model, method, payload)`` calls must be equal per event.
    """
    manager = ProjectionManager()
    manager._ensure_initialized()
    in_process: list[Call] = []
    _spy_on_handlers(list(manager._projections.values()), in_process)
    read_models = {type(p).__name__ for p in manager._projections.values()}

    service = create_coordinator_service(
        event_store=MagicMock(),
        projection_store=manager.store,
        realtime_projection=None,
        checkpoint_store=MagicMock(),
    )
    production_realtime = RealTimeProjection()
    production = [p for p in service._projections if type(_target(p)).__name__ in read_models] + [
        RealTimeProjectionAdapter(production_realtime)
    ]
    coordinated: list[Call] = []
    _spy_on_handlers([_target(p) for p in production], coordinated)
    coordinator = SubscriptionCoordinator(MagicMock(), _NoCheckpoints(), production)  # type: ignore[arg-type]

    event_types = sorted(
        set().union(*(p.get_subscribed_event_types() or set() for p in production))
    )
    assert "WorkflowCreated" in event_types and "ExecutionCancelled" in event_types

    for nonce, event_type in enumerate(event_types, 1):
        in_process.clear()
        coordinated.clear()
        await manager.process_event_envelope(_event(nonce, event_type))
        await coordinator.dispatch_event(_event(nonce, event_type))
        expected = sorted(coordinated, key=lambda c: (c[0], c[1]))
        actual = sorted(in_process, key=lambda c: (c[0], c[1]))
        assert expected, f"production handles {event_type} nowhere"
        assert actual == expected, f"{event_type}: test mode {actual} != production {expected}"


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
    from syn_adapters.subscriptions.read_model_dispatch import as_checkpointed

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
    assert "wf-legacy-2265" in [w.id for w in listed]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dashboard_total_workflows_follows_archive_and_reinstall_in_test_mode() -> None:
    """Archive and reinstall reach dashboard_metrics on the in-process path (#641)."""
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
        PhaseDefinition,
        WorkflowClassification,
        WorkflowType,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateArchivedEvent import (
        WorkflowTemplateArchivedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateUpdatedEvent import (
        WorkflowTemplateUpdatedEvent,
    )

    def template(workflow_id: str, event_type: type) -> object:
        return event_type(
            workflow_id=workflow_id,
            name=workflow_id,
            workflow_type=WorkflowType.RESEARCH,
            classification=WorkflowClassification.SIMPLE,
            repository_url="",
            repository_ref="main",
            phases=[PhaseDefinition(phase_id="p1", name="P1", order=1)],
        )

    from syn_adapters.projection_stores import reset_projection_store

    # Fresh store: the in-memory singleton is shared with every test on this
    # xdist worker, so other tests' templates would otherwise be counted (#2267).
    reset_projection_store()
    manager = ProjectionManager()
    before = (await manager.dashboard_metrics.get_metrics()).total_workflows
    for workflow_id in ("wf-641-1", "wf-641-2", "wf-641-3"):
        await manager.process_event_envelope(
            _envelope(
                template(workflow_id, WorkflowTemplateCreatedEvent), "WorkflowTemplateCreated"
            )
        )
    await manager.process_event_envelope(
        _envelope(WorkflowTemplateArchivedEvent(workflow_id="wf-641-2"), "WorkflowTemplateArchived")
    )
    assert (await manager.dashboard_metrics.get_metrics()).total_workflows == before + 2

    await manager.process_event_envelope(
        _envelope(template("wf-641-2", WorkflowTemplateUpdatedEvent), "WorkflowTemplateUpdated")
    )
    assert (await manager.dashboard_metrics.get_metrics()).total_workflows == before + 3
