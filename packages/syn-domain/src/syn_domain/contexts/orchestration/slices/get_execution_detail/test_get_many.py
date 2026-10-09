"""``get_many`` answers what ``get_by_id`` answers for each id, in one read (#1811)."""

from __future__ import annotations

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)

pytestmark = pytest.mark.unit


async def test_get_many_is_get_by_id_for_each_id() -> None:
    projection = WorkflowExecutionDetailProjection(InMemoryProjectionStore())
    for execution_id in ("exec-1", "exec-2"):
        await projection.on_workflow_execution_started(
            {
                "execution_id": execution_id,
                "workflow_id": "wf",
                "workflow_name": "wf",
                "phases": [{"phase_id": "p1", "name": "p1"}],
            }
        )

    many = await projection.get_many(["exec-1", "exec-2", "exec-missing"])

    assert set(many) == {"exec-1", "exec-2"}
    for execution_id, detail in many.items():
        assert detail == await projection.get_by_id(execution_id)
    assert await projection.get_many([]) == {}
