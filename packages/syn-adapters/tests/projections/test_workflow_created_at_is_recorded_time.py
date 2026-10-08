"""A workflow's created_at is when the store recorded its creation (#959).

The payload carries no clock, so the list and detail projections stored
``created_at=None`` for every template and the default ``-created_at`` sort
ordered nothing. The time comes from the envelope's ``recorded_time_unix_ms``.

These start from the bytes the gRPC store returns and decode them with the
production client, because that hop is where the time was lost a second time:
ESP v0.17.0 drops both stored clocks and ``EventMetadata`` defaults them to
``now()``. A test fed from ``MemoryEventStoreClient`` keeps its in-process
envelope and would pass without either fix. The recorded times below are years
in the past, so a value defaulted to the time of reading cannot match them.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from datetime import UTC, datetime

import pytest
from event_sourcing.proto.eventstore.v1 import eventstore_pb2
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.storage.legacy_tolerant_client import LegacyShapeTolerantGrpcClient
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    PhaseDefinition,
    WorkflowClassification,
    WorkflowType,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateCreatedEvent import (
    WorkflowTemplateCreatedEvent,
)
from syn_domain.contexts.orchestration.slices.get_workflow_detail.projection import (
    WorkflowDetailProjection,
)
from syn_domain.contexts.orchestration.slices.list_workflows.projection import (
    WorkflowListProjection,
)

OLDER = datetime(2025, 1, 2, 3, 4, 5, 678000, tzinfo=UTC)
NEWER = datetime(2025, 6, 7, 8, 9, 10, 111000, tzinfo=UTC)


def _stored(workflow_id: str, recorded: datetime, global_nonce: int) -> eventstore_pb2.EventData:
    """A WorkflowTemplateCreated as the gRPC store hands it back."""
    event = WorkflowTemplateCreatedEvent(
        workflow_id=workflow_id,
        name=workflow_id,
        workflow_type=WorkflowType.RESEARCH,
        classification=WorkflowClassification.SIMPLE,
        repository_url="",
        repository_ref="main",
        phases=[PhaseDefinition(phase_id="p1", name="P1", order=1)],
    )
    recorded_ms = int(recorded.timestamp() * 1000)
    meta = eventstore_pb2.EventMetadata(
        event_id=f"evt-{workflow_id}",
        aggregate_id=workflow_id,
        aggregate_type="WorkflowTemplate",
        aggregate_nonce=1,
        global_nonce=global_nonce,
        event_type="WorkflowTemplateCreated",
        event_version=1,
        content_type="application/json",
        # The client clock differs from the commit, so a test can tell which
        # one the projection used.
        timestamp_unix_ms=recorded_ms - 60_000,
        recorded_time_unix_ms=recorded_ms,
    )
    return eventstore_pb2.EventData(meta=meta, payload=event.model_dump_json().encode("utf-8"))


# Created OLDER first, as a store would number them.
STREAM = (_stored("wf-older", OLDER, 1), _stored("wf-newer", NEWER, 2))


async def _replay() -> tuple[WorkflowListProjection, WorkflowDetailProjection]:
    client = LegacyShapeTolerantGrpcClient(address="localhost:1", tenant_id="t")
    listing = WorkflowListProjection(InMemoryProjectionStore())
    detail = WorkflowDetailProjection(InMemoryProjectionStore())
    checkpoints = MemoryCheckpointStore()
    for stored in STREAM:
        envelope = client._proto_to_envelope(stored)  # pyright: ignore[reportPrivateUsage]
        for projection in (listing, detail):
            await projection.handle_event(envelope, checkpoints)
    return listing, detail


@pytest.mark.unit
class TestWorkflowCreatedAtIsRecordedTime:
    async def test_list_is_newest_first_by_recorded_time(self) -> None:
        listing, _ = await _replay()

        page = await listing.query()

        assert [(s.id, s.created_at) for s in page] == [
            ("wf-newer", NEWER.isoformat()),
            ("wf-older", OLDER.isoformat()),
        ]

    async def test_detail_carries_the_same_created_at(self) -> None:
        _, detail = await _replay()

        found = await detail.get_by_id("wf-older")

        assert found is not None
        assert found.created_at is not None
        # ISO 8601 in UTC, which is what the API passes through as a string.
        assert datetime.fromisoformat(str(found.created_at)) == OLDER

    async def test_replaying_twice_gives_identical_rows(self) -> None:
        first_list, first_detail = await _replay()
        second_list, second_detail = await _replay()

        assert [s.to_dict() for s in await first_list.query()] == [
            s.to_dict() for s in await second_list.query()
        ]
        for workflow_id in ("wf-older", "wf-newer"):
            first = await first_detail.get_by_id(workflow_id)
            second = await second_detail.get_by_id(workflow_id)
            assert first is not None
            assert second is not None
            assert first.to_dict() == second.to_dict()
