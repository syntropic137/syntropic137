"""Equal start times page by the execution id, never by write time (#1800 review).

The tie-break used to be ``updated_at``: rows A and B started at the same
instant, page size 1, page 1 shows A; then B's row is rewritten (a status
change), which moves it ahead of A, and page 2 shows A again while B is on no
page at all. The execution id never changes, so it is the tie-break.

The double reads ``get_all`` newest write first, the order the Postgres store
returns it in, which is what made the defect visible.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from typing import TYPE_CHECKING

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration._shared.execution_list_reads import (
    WORKFLOW_EXECUTIONS,
    ExecutionListReads,
)
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_summary import (
    WorkflowExecutionSummary,
)

if TYPE_CHECKING:
    from syn_domain.pagination import ProjectionRecord

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

STARTED = "2026-10-02T09:00:00+00:00"


class _NewestWriteFirst(InMemoryProjectionStore):
    """``get_all`` in ``updated_at DESC`` order, as Postgres reads it: a write moves a row first."""

    async def save(self, projection: str, key: str, data: ProjectionRecord) -> None:
        await super().save(projection, key, dict(data))
        rows = self._data[projection]  # pyright: ignore[reportPrivateUsage]  # the double's own state
        written = rows.pop(key)
        self._data[projection] = {key: written, **rows}  # pyright: ignore[reportPrivateUsage]


def _row(execution_id: str, status: str) -> WorkflowExecutionSummary:
    return WorkflowExecutionSummary(
        workflow_execution_id=execution_id,
        workflow_id="wf-1",
        workflow_name="wf",
        status=status,
        started_at=STARTED,
        completed_at=None,
        completed_phases=0,
        total_phases=1,
        total_tokens=0,
    )


async def test_updating_a_tied_row_between_pages_neither_repeats_nor_drops_a_row() -> None:
    store = _NewestWriteFirst()
    for execution_id in ("exec-a", "exec-b"):
        await store.save(WORKFLOW_EXECUTIONS, execution_id, _row(execution_id, "running").to_dict())
    reads = ExecutionListReads(store)

    page_1 = await reads.page(workflow_id="wf-1", offset=0, limit=1)
    await store.save(WORKFLOW_EXECUTIONS, "exec-b", _row("exec-b", "completed").to_dict())
    page_2 = await reads.page(workflow_id="wf-1", offset=1, limit=1)

    assert [r.workflow_execution_id for r in page_1.rows] == ["exec-a"]
    assert [r.workflow_execution_id for r in page_2.rows] == ["exec-b"]
