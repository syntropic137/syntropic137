"""`GET /executions/{id}/pushes` serves the `PhaseCommitPushed` events a run recorded (#1544).

The question it answers came up on a real run: did exec-8aad6f45c4b1's phases
record their pushes, and at which SHAs? Nothing served those events, so the only
way to tell was a hand query against the event store.

The stream is built by the aggregate's own commands and read back through JSON
into a fresh aggregate, as a repository read does, so a field the event or its
reader dropped would vanish here too. Two phases push, one twice, so a route
that served only the first push, or the last one, or merged phases, cannot pass.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from event_sourcing import DomainEvent, EventEnvelope
from fastapi import HTTPException

from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    RecordPhasePushCommand,
    StartExecutionCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    PhaseDefinition,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    CompletePhaseCommand,
    StartPhaseCommand,
    WorkflowExecutionAggregate,
)

pytestmark = pytest.mark.unit

EXECUTION_ID = "exec-1544-pushes"
WORKFLOW_ID = "wf-1544"
PHASES = (("implement", 1), ("verify", 2), ("fix", 3))
BRANCH = "fix/2042-large-text-artifacts"
IMPLEMENT_SHA = "a154a154a154a154a154a154a154a154a154a154"
FIX_FIRST_SHA = "b154b154b154b154b154b154b154b154b154b154"
FIX_LAST_SHA = "c154c154c154c154c154c154c154c154c154c154"


def _complete(aggregate: WorkflowExecutionAggregate, phase_id: str) -> None:
    aggregate.complete_phase(
        CompletePhaseCommand(
            execution_id=EXECUTION_ID,
            workflow_id=WORKFLOW_ID,
            phase_id=phase_id,
            session_id=None,
            artifact_id=None,
            input_tokens=0,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            total_tokens=0,
            duration_seconds=1.0,
        )
    )


def _push(aggregate: WorkflowExecutionAggregate, phase_id: str, sha: str) -> None:
    aggregate.record_phase_push(
        RecordPhasePushCommand(
            execution_id=EXECUTION_ID,
            phase_id=phase_id,
            repository="syntropic137",
            branch=BRANCH,
            sha=sha,
        )
    )


def _stored_stream(*, pushes: bool = True) -> list[EventEnvelope[DomainEvent]]:
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id=EXECUTION_ID,
            workflow_id=WORKFLOW_ID,
            workflow_name="pushes",
            total_phases=len(PHASES),
            inputs={"task": "record the pushes"},
            phase_definitions=[
                PhaseDefinition(phase_id=p, name=p.title(), order=o) for p, o in PHASES
            ],
        )
    )
    for phase_id, order in PHASES:
        aggregate.start_phase(
            StartPhaseCommand(
                execution_id=EXECUTION_ID,
                workflow_id=WORKFLOW_ID,
                phase_id=phase_id,
                phase_name=phase_id.title(),
                phase_order=order,
            )
        )
        if pushes and phase_id == "implement":
            _push(aggregate, "implement", IMPLEMENT_SHA)
        if pushes and phase_id == "fix":
            _push(aggregate, "fix", FIX_FIRST_SHA)
            _push(aggregate, "fix", FIX_LAST_SHA)
        if phase_id != "fix":
            _complete(aggregate, phase_id)
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

    async def exists(self, execution_id: str) -> bool:
        return execution_id == EXECUTION_ID

    async def get_by_id(self, execution_id: str) -> WorkflowExecutionAggregate | None:
        if execution_id != EXECUTION_ID:
            return None
        fresh = WorkflowExecutionAggregate()
        fresh.rehydrate(list(self.stream))
        return fresh


class _UnreadableRepository:
    async def exists(self, execution_id: str) -> bool:
        del execution_id
        raise ConnectionError("event store down")


def _serve(monkeypatch: pytest.MonkeyPatch, repository: object) -> None:
    from syn_api import _wiring

    monkeypatch.setattr(_wiring, "get_workflow_execution_repository", lambda: repository)


@pytest.mark.asyncio
async def test_serves_every_recorded_push_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    from syn_api.routes.executions.pushes import get_execution_pushes_endpoint

    _serve(monkeypatch, _Repository(_stored_stream()))
    response = await get_execution_pushes_endpoint(EXECUTION_ID)

    assert response.execution_id == EXECUTION_ID
    assert [(p.phase_id, p.repository, p.branch, p.sha) for p in response.pushes] == [
        ("implement", "syntropic137", BRANCH, IMPLEMENT_SHA),
        ("fix", "syntropic137", BRANCH, FIX_FIRST_SHA),
        ("fix", "syntropic137", BRANCH, FIX_LAST_SHA),
    ]


@pytest.mark.asyncio
async def test_no_recorded_push_is_an_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    from syn_api.routes.executions.pushes import get_execution_pushes_endpoint

    _serve(monkeypatch, _Repository(_stored_stream(pushes=False)))
    assert (await get_execution_pushes_endpoint(EXECUTION_ID)).pushes == []


@pytest.mark.asyncio
async def test_an_unreadable_store_is_503_not_an_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from syn_api.routes.executions.pushes import get_execution_pushes_endpoint

    _serve(monkeypatch, _UnreadableRepository())
    with pytest.raises(HTTPException) as raised:
        await get_execution_pushes_endpoint(EXECUTION_ID)
    assert raised.value.status_code == 503


@pytest.mark.asyncio
async def test_the_route_is_served_over_http() -> None:
    """Registered on the app, so the OpenAPI spec and the CLI types see it."""
    from syn_api.main import app

    paths = app.openapi()["paths"]
    get = paths["/executions/{execution_id}/pushes"]["get"]
    schema = get["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("/ExecutionPushesResponse")
