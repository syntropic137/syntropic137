"""A resume chain links both ways in both execution read models (#1881).

The history is the one #1696 pins: a fresh run that fails, its resume that
fails, and that resume's resume, each written by the real resume path and
dispatched through the real coordinator. Nothing here hand-builds an event, so
a lineage the domain stopped writing, or a read model that dropped it, fails.

The child side comes off its own `WorkflowExecutionStarted.resumed_from`, the
parent side off its own `ExecutionResumed`. A pre-rename `ExecutionForked`
links the same way, and a rebuild (clear, then replay from zero, what a
VERSION bump triggers) brings every link back.

The real-store replay of this sequence lives in
`packages/syn-domain/tests/integration/test_1881_resume_lineage_real_store.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.read_models.resume_lineage import ResumedFrom
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
    WorkflowExecutionDetail,
)
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_summary import (
    WorkflowExecutionSummary,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)
from syn_domain.contexts.orchestration.slices.list_executions.projection import (
    WorkflowExecutionListProjection,
)
from syn_domain.contexts.orchestration.slices.start_resume.test_1696_a_resumed_start_reaches_the_execution_read_models import (
    RESUME_OF_RESUME,
    _coordinator,
    _history,
)
from syn_domain.contexts.orchestration.slices.start_resume.test_start_resume import (
    PARENT,
    RESUME,
)

if TYPE_CHECKING:
    from event_sourcing import DomainEvent, EventEnvelope

pytestmark = pytest.mark.unit

DETAIL = WorkflowExecutionDetailProjection.PROJECTION_NAME
LIST = WorkflowExecutionListProjection.PROJECTION_NAME


def _resume_phase(history: list[EventEnvelope[DomainEvent]], child: str) -> str:
    """The phase ``child`` picked up at, as its parent's ExecutionResumed decided it."""
    for envelope in history:
        payload = envelope.event.model_dump()
        if (
            envelope.metadata.event_type == "ExecutionResumed"
            and payload["resume_execution_id"] == child
        ):
            return str(payload["resume_phase_id"])
    raise AssertionError(f"no ExecutionResumed admitted {child}")


async def _lineage(
    store: InMemoryProjectionStore, name: str, execution_id: str
) -> tuple[ResumedFrom | None, str | None]:
    row = await store.get(name, execution_id)
    assert row is not None, f"{name} has no row for {execution_id}"
    model = (
        WorkflowExecutionDetail.from_dict(row)
        if name == DETAIL
        else WorkflowExecutionSummary.from_dict(row)
    )
    return model.resumed_from, model.resumed_as


async def _assert_chain(store: InMemoryProjectionStore, history: list[EventEnvelope[DomainEvent]]):
    for name in (DETAIL, LIST):
        assert await _lineage(store, name, PARENT) == (None, RESUME)
        assert await _lineage(store, name, RESUME) == (
            ResumedFrom(PARENT, _resume_phase(history, RESUME)),
            RESUME_OF_RESUME,
        )
        assert await _lineage(store, name, RESUME_OF_RESUME) == (
            ResumedFrom(RESUME, _resume_phase(history, RESUME_OF_RESUME)),
            None,
        )


async def _dispatch(store: InMemoryProjectionStore, history: list[EventEnvelope[DomainEvent]]):
    coordinator = _coordinator(store)
    for envelope in history:
        await coordinator.dispatch_event(envelope)


class TestLineage:
    async def test_every_member_of_a_chain_links_to_its_neighbours(self) -> None:
        history = await _history()
        store = InMemoryProjectionStore()
        await _dispatch(store, history)
        await _assert_chain(store, history)

    async def test_a_rebuild_reproduces_every_link(self) -> None:
        """What a VERSION bump does to a deployment: clear, then replay from zero."""
        history = await _history()
        store = InMemoryProjectionStore()
        await _dispatch(store, history)
        await WorkflowExecutionDetailProjection(store).clear_all_data()
        await WorkflowExecutionListProjection(store).clear_all_data()
        assert await store.get_all(DETAIL) == []
        assert await store.get_all(LIST) == []

        await _dispatch(store, history)
        await _assert_chain(store, history)

    async def test_a_pre_rename_execution_forked_links_forward(self) -> None:
        """A resume stored before the rename names its child as `fork_execution_id`."""
        history = await _history()
        forked: list[EventEnvelope[DomainEvent]] = []
        legacy: list[tuple[str, dict[str, object]]] = []
        for envelope in history:
            if envelope.metadata.event_type == "ExecutionResumed":
                payload = envelope.event.model_dump(mode="json")
                payload["fork_execution_id"] = payload.pop("resume_execution_id")
                legacy.append((str(payload["execution_id"]), payload))
            else:
                forked.append(envelope)
        store = InMemoryProjectionStore()
        await _dispatch(store, forked)
        detail = WorkflowExecutionDetailProjection(store)
        listing = WorkflowExecutionListProjection(store)
        for _, payload in legacy:
            await detail.on_execution_forked(payload)
            await listing.on_execution_forked(payload)
        await _assert_chain(store, history)

    async def test_versions_were_bumped_so_history_rebuilds(self) -> None:
        assert WorkflowExecutionDetailProjection.VERSION >= 19
        assert WorkflowExecutionListProjection.VERSION >= 11
