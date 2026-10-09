"""A workflow's definition changes, dated by recorded time, for trend markers (#1788).

Fed through ``handle_event`` with real envelopes, the path the coordinator
uses, because the date comes from the envelope and a handler called directly
has none.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from datetime import UTC, datetime

import pytest
from event_sourcing import DomainEvent, EventEnvelope, EventMetadata
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    PhaseDefinition,
    WorkflowClassification,
    WorkflowType,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowPhaseUpdatedEvent import (
    WorkflowPhaseUpdatedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateCreatedEvent import (
    WorkflowTemplateCreatedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateUpdatedEvent import (
    WorkflowTemplateUpdatedEvent,
)
from syn_domain.contexts.orchestration.domain.read_models.workflow_definition_changes import (
    DefinitionChangeKind,
    WorkflowDefinitionChange,
)
from syn_domain.contexts.orchestration.slices.get_workflow_detail.projection import (
    WorkflowDetailProjection,
)

pytestmark = pytest.mark.unit

WF = "wf-verify"
T1 = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
T2 = datetime(2026, 9, 5, 9, 30, tzinfo=UTC)
T3 = datetime(2026, 9, 9, 12, 15, tzinfo=UTC)
_PHASES = [PhaseDefinition(phase_id="verify", name="Verify", order=1)]
_TEMPLATE = {
    "workflow_id": WF,
    "name": WF,
    "workflow_type": WorkflowType.RESEARCH,
    "classification": WorkflowClassification.SIMPLE,
    "repository_url": "",
    "repository_ref": "main",
    "phases": _PHASES,
}


def _envelope(event: DomainEvent, event_type: str, nonce: int, at: datetime) -> EventEnvelope:
    return EventEnvelope(
        event=event,
        metadata=EventMetadata(
            aggregate_id=WF,
            aggregate_type="WorkflowTemplate",
            aggregate_nonce=nonce,
            event_type=event_type,
            global_nonce=nonce,
            recorded_timestamp=at,
        ),
    )


def _stream() -> list[EventEnvelope]:
    return [
        _envelope(
            WorkflowTemplateCreatedEvent(**_TEMPLATE, version="1.0.0"),
            "WorkflowTemplateCreated",
            1,
            T1,
        ),
        _envelope(
            WorkflowPhaseUpdatedEvent(workflow_id=WF, phase_id="verify", prompt_template="v2"),
            "WorkflowPhaseUpdated",
            2,
            T2,
        ),
        _envelope(
            WorkflowTemplateUpdatedEvent(**_TEMPLATE, source_digest="d" * 40),
            "WorkflowTemplateUpdated",
            3,
            T3,
        ),
    ]


async def _replayed(times: int) -> WorkflowDetailProjection:
    projection = WorkflowDetailProjection(InMemoryProjectionStore())
    for _ in range(times):
        checkpoints = MemoryCheckpointStore()
        for envelope in _stream():
            await projection.handle_event(envelope, checkpoints)
    return projection


class TestDefinitionChanges:
    async def test_each_change_is_dated_and_versioned_like_its_runs(self) -> None:
        projection = await _replayed(times=1)

        history = await projection.definition_history(WF)

        assert history.changes == (
            WorkflowDefinitionChange(
                sequence=1,
                definition_version="1.0.0",
                changed_at=T1.isoformat(),
                kind=DefinitionChangeKind.CREATED,
            ),
            # A phase edit keeps the version: nothing new was installed.
            WorkflowDefinitionChange(
                sequence=2,
                definition_version="1.0.0",
                changed_at=T2.isoformat(),
                kind=DefinitionChangeKind.PHASE_UPDATED,
            ),
            # No package version: the source digest, as a run records it.
            WorkflowDefinitionChange(
                sequence=3,
                definition_version="d" * 40,
                changed_at=T3.isoformat(),
                kind=DefinitionChangeKind.UPDATED,
            ),
        )
        assert history.current_version == "d" * 40

    async def test_replaying_twice_records_each_change_once(self) -> None:
        once = await (await _replayed(times=1)).definition_history(WF)
        twice = await (await _replayed(times=2)).definition_history(WF)

        assert twice == once

    async def test_a_workflow_with_no_recorded_change_has_an_empty_history(self) -> None:
        projection = WorkflowDetailProjection(InMemoryProjectionStore())

        history = await projection.definition_history("wf-unknown")

        assert history.changes == ()
        assert history.current_version is None

    async def test_clearing_the_projection_clears_the_history(self) -> None:
        projection = await _replayed(times=1)

        await projection.clear_all_data()

        assert (await projection.definition_history(WF)).changes == ()


def _reinstall(version: str, nonce: int, at: datetime) -> EventEnvelope:
    return _envelope(
        WorkflowTemplateUpdatedEvent(**_TEMPLATE, version=version),
        "WorkflowTemplateUpdated",
        nonce,
        at,
    )


async def _fed(envelopes: list[EventEnvelope]) -> WorkflowDetailProjection:
    projection = WorkflowDetailProjection(InMemoryProjectionStore())
    checkpoints = MemoryCheckpointStore()
    for envelope in envelopes:
        await projection.handle_event(envelope, checkpoints)
    return projection


class TestChangeIdentityAndOrder:
    """A change is identified and ordered by stream position, never by time (#1800 review)."""

    async def test_two_reinstalls_in_the_same_millisecond_are_both_retained(self) -> None:
        created = _stream()[0]
        projection = await _fed([created, _reinstall("2.0.0", 2, T2), _reinstall("3.0.0", 3, T2)])

        history = await projection.definition_history(WF)

        assert [c.definition_version for c in history.changes] == ["1.0.0", "2.0.0", "3.0.0"]
        assert history.current_version == "3.0.0"

    async def test_a_clock_regression_keeps_stream_order_and_dates_lookups_right(self) -> None:
        oct1 = datetime(2026, 10, 1, tzinfo=UTC)
        oct2 = datetime(2026, 10, 2, tzinfo=UTC)
        oct3 = datetime(2026, 10, 3, tzinfo=UTC)
        created = _envelope(
            WorkflowTemplateCreatedEvent(**_TEMPLATE, version="1.0.0"),
            "WorkflowTemplateCreated",
            1,
            oct1,
        )
        # Recorded Oct 1, Oct 3, then Oct 2: the store's clock stepped back.
        projection = await _fed(
            [created, _reinstall("2.0.0", 2, oct3), _reinstall("3.0.0", 3, oct2)]
        )

        history = await projection.definition_history(WF)

        assert [c.sequence for c in history.changes] == [1, 2, 3]
        assert [c.definition_version for c in history.changes] == ["1.0.0", "2.0.0", "3.0.0"]
        # At Oct 2: changes 1 (Oct 1) and 3 (Oct 2) had been recorded; 3 is latest in the stream.
        assert history.version_at(oct2) == "3.0.0"
        assert history.version_at(oct1) == "1.0.0"
        assert history.version_at(oct3) == "3.0.0"
