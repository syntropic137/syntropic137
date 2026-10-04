"""What a phase had at start reaches `GET /executions/{id}` (#1454).

The owner's ask: "inside a workflow phase, I want to see which skills/tools were
available to the agent at the time". `WorkflowExecutionStarted` has pinned each
phase's tools, skills and model since #1454; no response carried them.

They are read from the stored start event (via the aggregate that replays it),
not from the detail projection, so no projection VERSION bump was needed and
executions started before this change show their pins at once.

WHY THE FIXTURE GOES THROUGH JSON. The aggregate is started by command, then
its events are serialised and replayed into a FRESH aggregate, which is what a
repository read does. A field the start event or its reader dropped would
vanish on that hop and nowhere else. And nothing is asserted on the aggregate:
the assertions are on the served response, after two more hand-listed
constructors (`PhaseExecution`, `PhaseExecutionInfo`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from event_sourcing import DomainEvent, EventEnvelope

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration._shared.resolved_skill import ResolvedSkill
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    StartExecutionCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
    PhaseDefinition,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)

if TYPE_CHECKING:
    from syn_api.routes.executions.models import ExecutionDetailResponse

pytestmark = pytest.mark.unit

EXECUTION_ID = "exec-1454-pins"

#: Values no default produces: a tool list a phase must have declared, a skill
#: at a specific tag and tree, and an explicit model.
TOOLS = ("Read", "Grep", "Bash(git log:*)")
SKILL = ResolvedSkill(
    skill_name="architecture",
    source_url="https://github.com/syntropic137/software-leverage-points",
    version="v2.3.1",
    resolved_sha="9f1c0de4",
    tree_storage_prefix="skills/9f1c0de4/",
)
MODEL = "claude-opus-5-5"


def _pinned() -> list[ExecutablePhase]:
    return [
        ExecutablePhase(
            phase_id="research",
            name="Research",
            order=1,
            prompt_template="look",
            agent_config=AgentConfiguration(model=MODEL, allowed_tools=TOOLS),
            skills=(SKILL,),
        )
    ]


def _start_command(pinned: list[ExecutablePhase] | None) -> StartExecutionCommand:
    return StartExecutionCommand(
        execution_id=EXECUTION_ID,
        workflow_id="wf-1454",
        workflow_name="pins",
        total_phases=1,
        inputs={"task": "show me the pins"},
        phase_definitions=[PhaseDefinition(phase_id="research", name="Research", order=1)],
        pinned_phases=pinned,
    )


def _stored_stream(pinned: list[ExecutablePhase] | None) -> list[EventEnvelope[DomainEvent]]:
    """The execution's events as the store returns them: through JSON."""
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(_start_command(pinned))
    return [
        EventEnvelope(
            event=type(e.event).model_validate_json(e.event.model_dump_json()),
            metadata=e.metadata,
        )
        for e in aggregate.get_uncommitted_events()
    ]


@dataclass
class _Repository:
    """`get_workflow_execution_repository()`, answering from a stored stream."""

    stream: list[EventEnvelope[DomainEvent]]

    async def get_by_id(self, execution_id: str) -> WorkflowExecutionAggregate | None:
        if execution_id != EXECUTION_ID:
            return None
        fresh = WorkflowExecutionAggregate()
        fresh.rehydrate(list(self.stream))
        return fresh


@dataclass
class _StubProjectionManager:
    store: InMemoryProjectionStore
    workflow_execution_detail: WorkflowExecutionDetailProjection


async def _served(
    monkeypatch: pytest.MonkeyPatch, pinned: list[ExecutablePhase] | None
) -> ExecutionDetailResponse:
    """Feed the projection and the repository the SAME stored start event."""
    from syn_api import _wiring
    from syn_api.routes.executions import queries

    stream = _stored_stream(pinned)
    store = InMemoryProjectionStore()
    projection = WorkflowExecutionDetailProjection(store)
    for envelope in stream:
        await projection.on_workflow_execution_started(envelope.event.model_dump())
    await projection.on_phase_started(
        {
            "execution_id": EXECUTION_ID,
            "workflow_id": "wf-1454",
            "phase_id": "research",
            "phase_name": "Research",
            "phase_order": 1,
            "started_at": "2026-10-04T09:00:00+00:00",
        }
    )
    manager = _StubProjectionManager(store=store, workflow_execution_detail=projection)

    async def _noop_connect() -> None:
        return None

    monkeypatch.setattr(queries, "ensure_connected", _noop_connect)
    monkeypatch.setattr(queries, "get_projection_mgr", lambda: manager)
    monkeypatch.setattr(_wiring, "get_projection_mgr", lambda: manager)
    monkeypatch.setattr(_wiring, "get_workflow_execution_repository", lambda: _Repository(stream))
    return await queries.get_execution_endpoint(EXECUTION_ID)


@pytest.mark.asyncio
async def test_a_phase_reports_the_tools_skills_and_model_it_started_with(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = await _served(monkeypatch, _pinned())

    (phase,) = response.phases
    pins = phase.pinned_at_start
    assert pins is not None, "a phase pinned at start was served as 'not recorded'"
    assert pins.allowed_tools == list(TOOLS)
    assert pins.requested_model == MODEL
    assert [(s.name, s.version, s.resolved_sha) for s in pins.skills] == [
        ("architecture", "v2.3.1", "9f1c0de4")
    ]


@pytest.mark.asyncio
async def test_an_execution_from_before_1454_reports_not_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Null, never an empty config: "had nothing" and "nobody wrote it down"
    are different answers, and only the second is true here."""
    response = await _served(monkeypatch, None)

    (phase,) = response.phases
    assert phase.pinned_at_start is None


@pytest.mark.asyncio
async def test_an_unreadable_stream_does_not_fail_the_detail_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pins decorate the read; losing them must not lose the execution."""
    from syn_api import _wiring

    class _Broken:
        async def get_by_id(self, execution_id: str) -> WorkflowExecutionAggregate | None:
            raise ConnectionError("event store down")

    response = await _served(monkeypatch, _pinned())
    monkeypatch.setattr(_wiring, "get_workflow_execution_repository", _Broken)
    from syn_api.routes.executions import queries

    response = await queries.get_execution_endpoint(EXECUTION_ID)

    (phase,) = response.phases
    assert phase.status == "running"
    assert phase.pinned_at_start is None
