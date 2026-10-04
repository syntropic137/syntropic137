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

import json
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
    from syn_api.routes.executions.models import ExecutionDetailResponse, PhaseExecutionInfo

pytestmark = pytest.mark.unit

EXECUTION_ID = "exec-1454-pins"

#: Values no default produces: a tool list a phase must have declared, a skill
#: at a specific tag and tree, and an explicit model. TWO phases with nothing in
#: common, so a reader that gave every phase the first one's pins (or swapped
#: them) cannot pass.
RESEARCH_TOOLS = ("Read", "Grep", "Bash(git log:*)")
RESEARCH_SKILL = ResolvedSkill(
    skill_name="architecture",
    source_url="https://github.com/syntropic137/software-leverage-points",
    version="v2.3.1",
    resolved_sha="9f1c0de4",
    tree_storage_prefix="skills/9f1c0de4/",
)
RESEARCH_MODEL = "claude-opus-5-5"
IMPLEMENT_TOOLS = ("Edit", "Write")
IMPLEMENT_SKILL = ResolvedSkill(
    skill_name="types",
    source_url="https://github.com/syntropic137/software-leverage-points",
    version="v1.0.0",
    resolved_sha="0badc0de",
    tree_storage_prefix="skills/0badc0de/",
)
IMPLEMENT_MODEL = "claude-sonnet-5"

PHASES = (("research", "Research", 1), ("implement", "Implement", 2))


def _pinned() -> list[ExecutablePhase]:
    return [
        ExecutablePhase(
            phase_id="research",
            name="Research",
            order=1,
            prompt_template="look",
            agent_config=AgentConfiguration(model=RESEARCH_MODEL, allowed_tools=RESEARCH_TOOLS),
            skills=(RESEARCH_SKILL,),
        ),
        ExecutablePhase(
            phase_id="implement",
            name="Implement",
            order=2,
            prompt_template="build",
            agent_config=AgentConfiguration(model=IMPLEMENT_MODEL, allowed_tools=IMPLEMENT_TOOLS),
            skills=(IMPLEMENT_SKILL,),
        ),
    ]


def _start_command(pinned: list[ExecutablePhase] | None) -> StartExecutionCommand:
    return StartExecutionCommand(
        execution_id=EXECUTION_ID,
        workflow_id="wf-1454",
        workflow_name="pins",
        total_phases=len(PHASES),
        inputs={"task": "show me the pins"},
        phase_definitions=[PhaseDefinition(phase_id=i, name=n, order=o) for i, n, o in PHASES],
        pinned_phases=pinned,
    )


def _through_json(event: DomainEvent, *, historical: bool) -> DomainEvent:
    """What the store returns. ``historical`` deletes ``pinned_phases`` from the
    stored payload, as an event written before #1454 never had the key at all -
    not a modern event that serialised it as null."""
    payload = json.loads(event.model_dump_json())
    if historical:
        payload.pop("pinned_phases", None)
    return type(event).model_validate(payload)


def _stored_stream(*, historical: bool = False) -> list[EventEnvelope[DomainEvent]]:
    """The execution's events as the store returns them: through JSON."""
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(_start_command(None if historical else _pinned()))
    return [
        EventEnvelope(event=_through_json(e.event, historical=historical), metadata=e.metadata)
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
    monkeypatch: pytest.MonkeyPatch, *, historical: bool = False
) -> ExecutionDetailResponse:
    """Feed the projection and the repository the SAME stored start event."""
    from syn_api import _wiring
    from syn_api.routes.executions import queries

    stream = _stored_stream(historical=historical)
    store = InMemoryProjectionStore()
    projection = WorkflowExecutionDetailProjection(store)
    for envelope in stream:
        await projection.on_workflow_execution_started(envelope.event.model_dump())
    for phase_id, name, order in PHASES:
        await projection.on_phase_started(
            {
                "execution_id": EXECUTION_ID,
                "workflow_id": "wf-1454",
                "phase_id": phase_id,
                "phase_name": name,
                "phase_order": order,
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


def _by_id(response: ExecutionDetailResponse) -> dict[str, PhaseExecutionInfo]:
    return {p.phase_id: p for p in response.phases}


@pytest.mark.asyncio
async def test_each_phase_reports_its_own_tools_skills_and_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    phases = _by_id(await _served(monkeypatch))
    assert set(phases) == {"research", "implement"}

    expected = {
        "research": (RESEARCH_TOOLS, RESEARCH_MODEL, ("architecture", "v2.3.1", "9f1c0de4")),
        "implement": (IMPLEMENT_TOOLS, IMPLEMENT_MODEL, ("types", "v1.0.0", "0badc0de")),
    }
    for phase_id, (tools, model, skill) in expected.items():
        phase = phases[phase_id]
        pins = phase.pinned_at_start
        assert pins is not None, f"{phase_id} was pinned at start but served without pins"
        assert phase.start_pins_status == "recorded"
        assert pins.allowed_tools == list(tools), phase_id
        assert pins.requested_model == model, phase_id
        assert [(s.name, s.version, s.resolved_sha) for s in pins.skills] == [skill], phase_id


@pytest.mark.asyncio
async def test_an_execution_from_before_1454_reports_not_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Null, never an empty config: "had nothing" and "nobody wrote it down"
    are different answers, and only the second is true here. The stored start
    event has no ``pinned_phases`` key at all, as a pre-#1454 event does not."""
    for phase in (await _served(monkeypatch, historical=True)).phases:
        assert phase.pinned_at_start is None
        assert phase.start_pins_status == "not_recorded"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "repository",
    [
        pytest.param(lambda: _Broken(), id="read-raises"),
        pytest.param(lambda: _Missing(), id="stream-missing"),
    ],
)
async def test_an_unreadable_stream_is_unavailable_not_unrecorded(
    monkeypatch: pytest.MonkeyPatch, repository: object
) -> None:
    """The pins decorate the read; losing them must not lose the execution,
    and must not be reported as "this run recorded nothing" either."""
    from syn_api import _wiring
    from syn_api.routes.executions import queries

    await _served(monkeypatch)
    monkeypatch.setattr(_wiring, "get_workflow_execution_repository", repository)

    response = await queries.get_execution_endpoint(EXECUTION_ID)

    assert len(response.phases) == len(PHASES)
    for phase in response.phases:
        assert phase.status == "running"
        assert phase.pinned_at_start is None
        assert phase.start_pins_status == "unavailable"


class _Broken:
    async def get_by_id(self, execution_id: str) -> WorkflowExecutionAggregate | None:
        raise ConnectionError("event store down")


class _Missing:
    async def get_by_id(self, execution_id: str) -> WorkflowExecutionAggregate | None:
        return None
