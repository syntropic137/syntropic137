"""PC-83: the producing agent survives a phase whose PhaseStarted was never projected.

`on_phase_completed` creates the row for a completion without a start, the
salvage path #1300 exists for. `AgentExecutionCompleted` arrives BEFORE that
row exists, so without holding its identity until then the row would name no
agent - on the rare path, while the common one names it (#1300's defect shape).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.events.AgentExecutionCompletedEvent import (
    AgentExecutionCompletedEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
    ExecutionJournal,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)

pytestmark = pytest.mark.unit


async def test_a_completion_without_a_start_names_the_agent_that_produced_it() -> None:
    projection = WorkflowExecutionDetailProjection(InMemoryProjectionStore())
    await projection.on_workflow_execution_started(
        {"execution_id": "exec-1", "workflow_id": "wf", "workflow_name": "wf"}
    )
    completed = AgentExecutionCompletedEvent(
        workflow_id="wf",
        execution_id="exec-1",
        phase_id="p1",
        session_id="s1",
        completed_at=datetime(2026, 10, 6, tzinfo=UTC),
        agent_provider="codex",
        agent_model="gpt-sol",
    )
    # The stored shape, as the journal writes it - not the model object.
    await projection.on_agent_execution_completed(ExecutionJournal._serialize_event(completed))
    await projection.on_phase_completed(
        {
            "execution_id": "exec-1",
            "phase_id": "p1",
            "input_tokens": 10,
            "output_tokens": 3,
            "completed_at": "2026-10-06T00:00:20Z",
        }
    )

    row = await projection._store.get(projection.PROJECTION_NAME, "exec-1")
    (phase,) = row["phases"]
    assert phase["status"] == "completed"
    assert (phase["agent_provider"], phase["agent_model"]) == ("codex", "gpt-sol")
