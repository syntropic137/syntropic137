"""#2141: a command Phase reaches a client as zero tokens and zero cost (ADR-078 D7).

A command Phase writes no Lane 2 ``session_summary`` and no ``token_usage``
rows, so it has nothing to price. That is only true for a client if every hop
between the event and the response agrees: the processor's ``PhaseCompleted``,
the detail projection, and the response mapping. The domain test
(``test_2141_a_command_phase_runs_through_the_processor.py``) stops at the
events; this one feeds the events a real run wrote through the real detail
projection and maps them as the API does.
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.workspace_backends.memory import MemoryEventStreamAdapter
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService
from syn_api.routes.executions.phase_mapping import _map_phase_detail, _map_phase_to_response
from syn_domain.contexts.agent_sessions.domain.events.agent_observation import ObservationType
from syn_domain.contexts.orchestration._shared.command_phase import (
    BoundedCommandResult,
    CommandStep,
    CommandTerminal,
    PhaseKind,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
    WorkflowExecutionDetail,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
    ExecutionJournal,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)
from syn_domain.testing.fake_session_repository import FakeSessionRepository

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from event_sourcing import DomainEvent, EventEnvelope

    from syn_api.routes.executions.models import PhaseExecutionInfo
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationHandle,
    )

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

os.environ.setdefault("APP_ENVIRONMENT", "test")

EXECUTION = "exec-2141-cost"


class _Steps(MemoryEventStreamAdapter):
    """Answers every step with the exit code its ``run`` line is mapped to, else 0."""

    def __init__(self, exit_codes: dict[str, int]) -> None:
        super().__init__()
        self.exit_codes = exit_codes

    async def run_bounded(
        self,
        handle: IsolationHandle,
        command: list[str],
        *,
        timeout_seconds: int,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
        tail_bytes: int = 8192,
        withheld: Callable[[], Iterable[str]] | None = None,
    ) -> BoundedCommandResult:
        return BoundedCommandResult(
            terminal=CommandTerminal.EXITED,
            exit_code=self.exit_codes.get(command[-1], 0),
            duration_ms=10,
        )


class _Stream:
    """The execution repository, keeping every envelope the run committed."""

    def __init__(self) -> None:
        self.envelopes: list[EventEnvelope[DomainEvent]] = []

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        self.envelopes.extend(aggregate.get_uncommitted_events())
        aggregate.mark_events_as_committed()

    async def save_new(self, aggregate: WorkflowExecutionAggregate) -> None:
        await self.save(aggregate)

    async def get_by_id(self, aggregate_id: str) -> WorkflowExecutionAggregate | None:
        return None


class _Lane2:
    """The observability writer: every row a run sends to Lane 2, where cost is priced."""

    def __init__(self) -> None:
        self.types: list[str] = []

    async def record_observation(
        self,
        session_id: str,
        observation_type: object,
        data: object,
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        self.types.append(str(getattr(observation_type, "value", observation_type)))


class _NoTimeline:
    async def get_session_tools(self, _session_id: str) -> None:
        return None


def _phases() -> list[ExecutablePhase]:
    return [
        ExecutablePhase(
            phase_id=phase_id,
            name=phase_id.title(),
            order=order,
            kind=PhaseKind.COMMAND,
            commands=(CommandStep(name=phase_id, run=f"make {phase_id}"),),
            timeout_seconds=600,
            clone_repos=False,
        )
        for order, phase_id in enumerate(("build", "test"), start=1)
    ]


async def _run(exit_codes: dict[str, int], lane2: _Lane2 | None = None) -> _Stream:
    stream = _Stream()
    workspace_service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY)
    workspace_service._event_stream = _Steps(exit_codes)  # pyright: ignore[reportPrivateUsage]
    processor = WorkflowExecutionProcessor(
        execution_repository=stream,  # pyright: ignore[reportArgumentType]
        session_repository=FakeSessionRepository(),
        workspace_service=workspace_service,
        artifact_repository=AsyncMock(),
        artifact_content_storage=None,
        artifact_query=None,
        conversation_storage=None,
        observability_writer=lane2,
        controller=None,
        prompt_builder=AsyncMock(return_value=""),
        command_builder=MagicMock(return_value=[]),
        todo_projection=ExecutionTodoProjection(store=InMemoryProjectionStore()),
        agent_handler=None,
    )
    await processor.run(
        workflow_id="wf-2141",
        workflow_name="Command phases",
        phases=_phases(),
        inputs={},
        execution_id=EXECUTION,
    )
    return stream


async def _as_a_client_sees_it(
    stream: _Stream,
) -> tuple[WorkflowExecutionDetail, list[PhaseExecutionInfo]]:
    store = InMemoryProjectionStore()
    projection = WorkflowExecutionDetailProjection(store)
    for envelope in stream.envelopes:
        name = getattr(envelope.event, "event_type", type(envelope.event).__name__)
        handler = getattr(
            projection,
            ExecutionJournal._event_type_to_handler(name),  # pyright: ignore[reportPrivateUsage]
            None,
        )
        if handler:
            await handler(ExecutionJournal._serialize_event(envelope.event))  # pyright: ignore[reportPrivateUsage]
    record = await store.get(WorkflowExecutionDetailProjection.PROJECTION_NAME, EXECUTION)
    assert record is not None, "the projection must have stored the execution"
    detail = WorkflowExecutionDetail.from_dict(record)
    phases = [
        _map_phase_to_response(await _map_phase_detail(p, _NoTimeline(), {}))  # pyright: ignore[reportArgumentType]
        for p in detail.phases
    ]
    return detail, phases


def _assert_free(phase: PhaseExecutionInfo) -> None:
    assert phase.session_id is None, "a command phase has no agent session"
    assert phase.cost_usd == Decimal("0")
    assert phase.total_tokens == 0
    assert (phase.input_tokens, phase.output_tokens) == (0, 0)
    assert (phase.cache_creation_tokens, phase.cache_read_tokens) == (0, 0)


async def test_a_completed_command_run_reaches_a_client_at_zero_cost() -> None:
    detail, phases = await _as_a_client_sees_it(await _run({}))

    assert detail.status == "completed"
    assert [p.phase_id for p in phases] == ["build", "test"]
    for phase in phases:
        _assert_free(phase)
        assert phase.duration_seconds is not None, "the real duration is kept"
    _assert_no_tokens(detail)


async def test_a_gate_failed_run_reaches_a_client_at_zero_cost() -> None:
    detail, phases = await _as_a_client_sees_it(await _run({"make build": 2}))

    assert detail.status == "failed"
    assert [p.phase_id for p in phases][:1] == ["build"]
    for phase in phases:
        _assert_free(phase)
    _assert_no_tokens(detail)


def _assert_no_tokens(detail: WorkflowExecutionDetail) -> None:
    """The execution's Lane 1 totals; its cost is merged from Lane 2 at the API,
    where a command phase wrote nothing."""
    totals = (
        detail.total_input_tokens,
        detail.total_output_tokens,
        detail.total_cache_creation_tokens,
        detail.total_cache_read_tokens,
    )
    assert totals == (0, 0, 0, 0)


@pytest.mark.parametrize("exit_codes", [{}, {"make build": 2}], ids=["completed", "gate-failed"])
async def test_a_command_run_sends_nothing_cost_is_priced_from(exit_codes: dict[str, int]) -> None:
    """The client's 0 is only true if Lane 2 got no usage to price (ADR-078 D7):
    the API merges cost from there, so this is the half the mapping cannot see."""
    lane2 = _Lane2()

    await _run(exit_codes, lane2)

    priced_from = {ObservationType.TOKEN_USAGE.value, ObservationType.COMPLETED.value}
    assert priced_from.isdisjoint(lane2.types), lane2.types
