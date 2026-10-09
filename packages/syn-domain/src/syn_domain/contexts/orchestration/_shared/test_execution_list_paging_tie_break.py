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

from typing import Any

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration._shared.execution_list_reads import (
    WORKFLOW_EXECUTIONS,
    ExecutionListReads,
)
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_summary import (
    WorkflowExecutionSummary,
)

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

STARTED = "2026-10-02T09:00:00+00:00"


class _NewestWriteFirst(InMemoryProjectionStore):
    """``get_all`` in ``updated_at DESC`` order, as Postgres reads it."""

    def __init__(self) -> None:
        super().__init__()
        self._writes: list[str] = []

    async def save(self, projection: str, key: str, data: dict[str, Any]) -> None:
        await super().save(projection, key, data)
        if key in self._writes:
            self._writes.remove(key)
        self._writes.append(key)

    async def get_all(self, projection: str) -> list[dict[str, Any]]:
        stored = {d["workflow_execution_id"]: d for d in await super().get_all(projection)}
        return [stored[key] for key in reversed(self._writes) if key in stored]


def _row(execution_id: str, status: str) -> dict[str, Any]:
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
    ).to_dict()


async def test_updating_a_tied_row_between_pages_neither_repeats_nor_drops_a_row() -> None:
    store = _NewestWriteFirst()
    for execution_id in ("exec-a", "exec-b"):
        await store.save(WORKFLOW_EXECUTIONS, execution_id, _row(execution_id, "running"))
    reads = ExecutionListReads(store)

    page_1 = await reads.page(workflow_id="wf-1", offset=0, limit=1)
    await store.save(WORKFLOW_EXECUTIONS, "exec-b", _row("exec-b", "completed"))
    page_2 = await reads.page(workflow_id="wf-1", offset=1, limit=1)

    assert [r.workflow_execution_id for r in page_1.rows] == ["exec-a"]
    assert [r.workflow_execution_id for r in page_2.rows] == ["exec-b"]
