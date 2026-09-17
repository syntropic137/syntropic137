"""Tests for RecordOperation handler.

The handler's body was a comment describing what it would do followed by
``pass`` (#1034), so every test here has to assert against what was
PERSISTED, never against the command that went in.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.agent_sessions._shared.value_objects import OperationType
from syn_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
    AgentSessionAggregate,
)
from syn_domain.contexts.agent_sessions.domain.commands.RecordOperationCommand import (
    RecordOperationCommand,
)
from syn_domain.contexts.agent_sessions.domain.commands.StartSessionCommand import (
    StartSessionCommand,
)
from syn_domain.contexts.agent_sessions.domain.events.agent_observation import ObservationType
from syn_domain.testing.fake_session_repository import FakeSessionRepository

from .RecordOperationHandler import _OBSERVATION_TYPES, RecordOperationHandler


class _FakeObservations:
    """Stands in for the session's telemetry lane, remembering what reached it."""

    def __init__(self) -> None:
        self.recorded: list[tuple[str, str, dict[str, object]]] = []

    async def record_observation(
        self,
        session_id: str,
        observation_type: ObservationType | str,
        data: dict[str, object],
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        self.recorded.append((session_id, str(observation_type), data))


async def _running_session(repo: FakeSessionRepository, session_id: str) -> None:
    session = AgentSessionAggregate()
    session.start_session(
        StartSessionCommand(
            aggregate_id=session_id,
            workflow_id="wf-record-op",
            execution_id="exec-record-op",
            phase_id="phase-1",
            agent_provider="claude",
        )
    )
    await repo.save(session)


def _tool_completed(session_id: str) -> RecordOperationCommand:
    return RecordOperationCommand(
        aggregate_id=session_id,
        operation_type=OperationType.TOOL_EXECUTION_COMPLETED,
        tool_name="Bash",
        tool_use_id="toolu_slice_1034",
        tool_output="slice-1034-output",
        duration_seconds=1.5,
        input_tokens=4000,
        output_tokens=321,
        total_tokens=4321,
    )


@pytest.mark.unit
async def test_handler_persists_the_operation() -> None:
    """The operation must be on the aggregate the repository holds afterwards."""
    repo = FakeSessionRepository()
    await _running_session(repo, "sess-record-1")

    await RecordOperationHandler(repository=repo, observations=_FakeObservations()).handle(
        _tool_completed("sess-record-1")
    )

    persisted = await repo.get_by_id("sess-record-1")
    assert persisted is not None
    assert persisted.operation_count == 1
    operation = persisted.operations[0]
    assert operation.operation_type == OperationType.TOOL_EXECUTION_COMPLETED
    assert operation.tool_name == "Bash"
    assert operation.tool_use_id == "toolu_slice_1034"
    assert operation.tool_output == "slice-1034-output"
    assert persisted.tokens.total_tokens == 4321


@pytest.mark.unit
async def test_handler_emits_the_event_for_downstream_readers() -> None:
    """Persisting is not enough: the OperationRecorded event is what every
    projection and the realtime stream actually consume."""
    repo = FakeSessionRepository()
    await _running_session(repo, "sess-record-2")

    await RecordOperationHandler(repository=repo, observations=_FakeObservations()).handle(
        _tool_completed("sess-record-2")
    )

    events = repo.recorded_events("sess-record-2")
    assert [type(e).__name__ for e in events] == ["SessionStartedEvent", "OperationRecordedEvent"]
    recorded = events[-1]
    assert recorded.tool_use_id == "toolu_slice_1034"
    assert recorded.tool_output == "slice-1034-output"
    assert recorded.total_tokens == 4321


@pytest.mark.unit
async def test_unknown_session_is_an_error_not_a_silent_no_op() -> None:
    """The no-op the handler replaced swallowed every command it was given."""
    repo = FakeSessionRepository()

    with pytest.raises(ValueError, match="not found"):
        await RecordOperationHandler(repository=repo, observations=_FakeObservations()).handle(
            _tool_completed("sess-missing")
        )

    assert repo.streams == {}


@pytest.mark.unit
async def test_aggregate_still_owns_the_rules() -> None:
    """A completed session refuses more operations, and the handler does not
    paper over the refusal by saving anyway."""
    from syn_domain.contexts.agent_sessions.domain.commands.CompleteSessionCommand import (
        CompleteSessionCommand,
    )

    repo = FakeSessionRepository()
    await _running_session(repo, "sess-record-3")
    completed = await repo.get_by_id("sess-record-3")
    assert completed is not None
    completed.complete_session(CompleteSessionCommand(aggregate_id="sess-record-3", success=True))
    await repo.save(completed)

    with pytest.raises(ValueError, match="session is completed"):
        await RecordOperationHandler(repository=repo, observations=_FakeObservations()).handle(
            _tool_completed("sess-record-3")
        )

    reread = await repo.get_by_id("sess-record-3")
    assert reread is not None
    assert reread.operation_count == 0


@pytest.mark.unit
async def test_the_operation_also_reaches_the_lane_the_read_path_serves() -> None:
    """Persisting and emitting are both Lane 1. ``GET /sessions/{id}`` builds
    ``operations`` from the observation lane alone (#1034), so an operation
    that never lands there is unreadable however correctly it was stored.
    """
    repo = FakeSessionRepository()
    await _running_session(repo, "sess-record-4")
    observations = _FakeObservations()

    await RecordOperationHandler(repository=repo, observations=observations).handle(
        _tool_completed("sess-record-4")
    )

    assert len(observations.recorded) == 1
    session_id, observation_type, data = observations.recorded[0]
    assert session_id == "sess-record-4"
    assert observation_type == ObservationType.TOOL_EXECUTION_COMPLETED
    assert data["tool_use_id"] == "toolu_slice_1034"
    assert data["output_preview"] == "slice-1034-output"
    assert data["duration_ms"] == 1500


@pytest.mark.unit
async def test_a_token_roll_up_is_not_a_timeline_row() -> None:
    """MESSAGE_RESPONSE carries a phase's token totals, and the agent's own
    stream has already written those tokens to the observation lane as
    ``token_usage``. Copying them there again would not add an operation - it
    would double the session's cost, which is priced off that lane.
    """
    repo = FakeSessionRepository()
    await _running_session(repo, "sess-record-5")
    observations = _FakeObservations()

    await RecordOperationHandler(repository=repo, observations=observations).handle(
        RecordOperationCommand(
            aggregate_id="sess-record-5",
            operation_type=OperationType.MESSAGE_RESPONSE,
            input_tokens=4000,
            output_tokens=321,
            total_tokens=4321,
        )
    )

    persisted = await repo.get_by_id("sess-record-5")
    assert persisted is not None
    assert persisted.tokens.total_tokens == 4321
    assert observations.recorded == []


@pytest.mark.unit
def test_every_operation_type_states_where_it_lands() -> None:
    """A missing entry would read as "not on the timeline" - the silence this
    change exists to remove. The map is total so an omission is a loud error.
    """
    assert set(_OBSERVATION_TYPES) == set(OperationType)


@pytest.mark.unit
async def test_a_telemetry_failure_does_not_lose_the_domain_write() -> None:
    """The aggregate has already committed when the lane is written. Failing
    the command afterwards would trade a visible operation for a lost one.
    """

    class _Broken(_FakeObservations):
        async def record_observation(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("timescale is down")

    repo = FakeSessionRepository()
    await _running_session(repo, "sess-record-6")

    await RecordOperationHandler(repository=repo, observations=_Broken()).handle(
        _tool_completed("sess-record-6")
    )

    persisted = await repo.get_by_id("sess-record-6")
    assert persisted is not None
    assert persisted.operation_count == 1
