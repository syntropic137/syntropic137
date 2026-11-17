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

import os
from dataclasses import dataclass

os.environ.setdefault("APP_ENVIRONMENT", "test")

import pytest
from event_sourcing import DomainEvent, EventEnvelope
from httpx import ASGITransport, AsyncClient, Response

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
#: Each push its own repository and branch, so a route that reused one push's
#: fields for another, or swapped two of them, cannot pass.
IMPLEMENT = ("syntropic137", "feat/2042-large-text-artifacts")
FIX_FIRST = ("syntropic137", "fix/2042-large-text-artifacts")
FIX_LAST = ("agentic-workspace", "fix/aw-2042-artifact-limit")
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


def _push(
    aggregate: WorkflowExecutionAggregate, phase_id: str, where: tuple[str, str], sha: str
) -> None:
    repository, branch = where
    aggregate.record_phase_push(
        RecordPhasePushCommand(
            execution_id=EXECUTION_ID,
            phase_id=phase_id,
            repository=repository,
            branch=branch,
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
            _push(aggregate, "implement", IMPLEMENT, IMPLEMENT_SHA)
        if pushes and phase_id == "fix":
            _push(aggregate, "fix", FIX_FIRST, FIX_FIRST_SHA)
            _push(aggregate, "fix", FIX_LAST, FIX_LAST_SHA)
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


class _VanishedRepository:
    """Says the stream exists, then reads back no aggregate."""

    async def exists(self, execution_id: str) -> bool:
        return execution_id == EXECUTION_ID

    async def get_by_id(self, execution_id: str) -> WorkflowExecutionAggregate | None:
        del execution_id
        return None


class _UnreadableRepository:
    async def exists(self, execution_id: str) -> bool:
        del execution_id
        raise ConnectionError("event store down")


def _serve(monkeypatch: pytest.MonkeyPatch, repository: object) -> None:
    from syn_api import _wiring

    monkeypatch.setattr(_wiring, "get_workflow_execution_repository", lambda: repository)


async def _get(monkeypatch: pytest.MonkeyPatch, repository: object, execution_id: str) -> Response:
    """Over HTTP through the real app, so routing and serialisation are exercised."""
    from syn_api import _wiring
    from syn_api.main import create_app

    monkeypatch.setattr(_wiring, "get_workflow_execution_repository", lambda: repository)
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        return await c.get(f"/executions/{execution_id}/pushes")


@pytest.mark.asyncio
async def test_serves_every_recorded_push_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    response = await _get(monkeypatch, _Repository(_stored_stream()), EXECUTION_ID)

    assert response.status_code == 200
    assert response.json() == {
        "execution_id": EXECUTION_ID,
        "pushes": [
            {
                "phase_id": "implement",
                "repository": IMPLEMENT[0],
                "branch": IMPLEMENT[1],
                "sha": IMPLEMENT_SHA,
            },
            {
                "phase_id": "fix",
                "repository": FIX_FIRST[0],
                "branch": FIX_FIRST[1],
                "sha": FIX_FIRST_SHA,
            },
            {
                "phase_id": "fix",
                "repository": FIX_LAST[0],
                "branch": FIX_LAST[1],
                "sha": FIX_LAST_SHA,
            },
        ],
    }


@pytest.mark.asyncio
async def test_no_recorded_push_is_an_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    response = await _get(monkeypatch, _Repository(_stored_stream(pushes=False)), EXECUTION_ID)
    assert response.status_code == 200
    assert response.json()["pushes"] == []


@pytest.mark.asyncio
async def test_an_unreadable_store_is_503_not_an_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = await _get(monkeypatch, _UnreadableRepository(), EXECUTION_ID)
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_a_stream_that_reads_back_empty_is_404(monkeypatch: pytest.MonkeyPatch) -> None:
    """The id resolves, but the repository returns no aggregate: 404, never an empty 200."""
    response = await _get(monkeypatch, _VanishedRepository(), EXECUTION_ID)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_the_route_is_in_the_openapi_spec() -> None:
    """With its response model, so the generated CLI types see it."""
    from syn_api.main import app

    paths = app.openapi()["paths"]
    get = paths["/executions/{execution_id}/pushes"]["get"]
    schema = get["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("/ExecutionPushesResponse")
