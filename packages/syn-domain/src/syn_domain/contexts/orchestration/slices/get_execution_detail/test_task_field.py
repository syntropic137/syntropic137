"""Task from inputs must survive event -> projection -> get_by_id (#1075).

Uses the real MemoryProjectionStore rather than a save()-call-args mock: a
mock that only inspects what was passed to save() can't catch a to_dict() or
from_dict() that silently drops the field one hop after it was written
correctly. Reading back through get_by_id() exercises the actual consumer.
"""

import os

import pytest
from event_sourcing.stores.memory_projection import MemoryProjectionStore

from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)


@pytest.mark.unit
class TestTaskFieldRoundTrip:
    @pytest.mark.asyncio
    async def test_task_survives_event_to_get_by_id_round_trip(self) -> None:
        os.environ["TEST_ENV"] = "true"
        store = MemoryProjectionStore()
        projection = WorkflowExecutionDetailProjection(store)

        await projection.on_workflow_execution_started(
            {
                "execution_id": "exec-task-detail-1",
                "workflow_id": "workflow-1",
                "workflow_name": "Test Workflow",
                "started_at": "2024-12-04T10:00:00Z",
                "inputs": {"task": "Fix issue #1075 in the syntropic137 repo"},
            }
        )

        result = await projection.get_by_id("exec-task-detail-1")

        assert result is not None
        assert result.task == "Fix issue #1075 in the syntropic137 repo"

    @pytest.mark.asyncio
    async def test_missing_task_in_inputs_yields_none(self) -> None:
        os.environ["TEST_ENV"] = "true"
        store = MemoryProjectionStore()
        projection = WorkflowExecutionDetailProjection(store)

        await projection.on_workflow_execution_started(
            {
                "execution_id": "exec-task-detail-2",
                "workflow_id": "workflow-1",
                "workflow_name": "Test Workflow",
                "started_at": "2024-12-04T10:00:00Z",
                "inputs": {},
            }
        )

        result = await projection.get_by_id("exec-task-detail-2")

        assert result is not None
        assert result.task is None
