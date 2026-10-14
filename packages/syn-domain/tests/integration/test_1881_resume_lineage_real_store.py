"""Resume lineage survives the REAL event store and a rebuild from it (#1881).

The unit test dispatches the resume history straight from the domain. This
appends that same history, written by the real resume path, to the ESP server,
reads it back with `read_all` the way a catch-up does, and replays what came
back through the real coordinator into both execution read models - twice,
the second time after clearing them, which is what a VERSION bump does to a
deployment. #1696 showed a resumed start can go missing between the store and
a read model; this is the hop the unit test cannot see.

Ids are made unique per run, so this never collides with other streams in a
shared test store.

    uv run pytest -m integration \\
        packages/syn-domain/tests/integration/test_1881_resume_lineage_real_store.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
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
    from event_sourcing import DomainEvent, EventEnvelope, GrpcEventStoreClient

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_STREAM_TYPE = "WorkflowExecution"


def _renamed(
    history: list[EventEnvelope[DomainEvent]], ids: dict[str, str]
) -> list[EventEnvelope[DomainEvent]]:
    """The same history under fresh execution ids, so each run owns its streams."""
    out: list[EventEnvelope[DomainEvent]] = []
    for envelope in history:
        raw = envelope.event.model_dump_json()
        for old, new in ids.items():
            raw = raw.replace(f'"{old}"', f'"{new}"')
        event = type(envelope.event).model_validate_json(raw)
        aggregate_id = ids.get(envelope.metadata.aggregate_id, envelope.metadata.aggregate_id)
        metadata = envelope.metadata.model_copy(
            update={"aggregate_id": aggregate_id, "global_nonce": None}
        )
        out.append(envelope.model_copy(update={"event": event, "metadata": metadata}))
    return out


async def _round_trip(
    client: GrpcEventStoreClient, history: list[EventEnvelope[DomainEvent]], ids: set[str]
) -> list[EventEnvelope[DomainEvent]]:
    """Append in domain order, then read back every event of these streams via read_all.

    Each event is appended alone, so its stream's head is the event's own
    aggregate nonce minus one: `None` means 0, which only the first fits.
    """
    for envelope in history:
        await client.append_events(
            f"{_STREAM_TYPE}-{envelope.metadata.aggregate_id}",
            [envelope],
            expected_version=envelope.metadata.aggregate_nonce - 1,
        )
    back: list[EventEnvelope[DomainEvent]] = []
    nonce = 0
    while True:
        page, is_end, next_nonce = await client.read_all(from_global_nonce=nonce, max_count=500)
        back.extend(e for e in page if e.metadata.aggregate_id in ids)
        if is_end or not page:
            break
        nonce = next_nonce
    return back


async def _lineage(
    store: InMemoryProjectionStore, execution_id: str
) -> list[tuple[str | None, str | None]]:
    """(parent, child) as each read model holds it."""
    detail_row = await store.get(WorkflowExecutionDetailProjection.PROJECTION_NAME, execution_id)
    list_row = await store.get(WorkflowExecutionListProjection.PROJECTION_NAME, execution_id)
    assert detail_row is not None and list_row is not None, f"no rows for {execution_id}"
    detail = WorkflowExecutionDetail.from_dict(detail_row)
    summary = WorkflowExecutionSummary.from_dict(list_row)
    return [
        (m.resumed_from.parent_execution_id if m.resumed_from else None, m.resumed_as)
        for m in (detail, summary)
    ]


async def test_a_resume_chain_read_back_from_the_store_links_both_ways(
    grpc_client: GrpcEventStoreClient,
) -> None:
    suffix = uuid4().hex[:8]
    ids = {old: f"{old}-{suffix}" for old in (PARENT, RESUME, RESUME_OF_RESUME)}
    a, b, c = ids[PARENT], ids[RESUME], ids[RESUME_OF_RESUME]
    back = await _round_trip(grpc_client, _renamed(await _history(), ids), set(ids.values()))
    assert [e.metadata.event_type for e in back].count("WorkflowExecutionStarted") == 3
    assert [e.metadata.event_type for e in back].count("ExecutionResumed") == 2

    store = InMemoryProjectionStore()
    for attempt in ("live", "rebuild"):
        if attempt == "rebuild":
            await WorkflowExecutionDetailProjection(store).clear_all_data()
            await WorkflowExecutionListProjection(store).clear_all_data()
        coordinator = _coordinator(store)
        for envelope in back:
            await coordinator.dispatch_event(envelope)

        assert await _lineage(store, a) == [(None, b)] * 2, attempt
        assert await _lineage(store, b) == [(a, c)] * 2, attempt
        assert await _lineage(store, c) == [(b, None)] * 2, attempt
