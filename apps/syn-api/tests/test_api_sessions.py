"""Tests for syn_api.routes.sessions — start, list, complete cycle.

Uses APP_ENVIRONMENT=test for in-memory adapters.
"""

import asyncio
import os

import pytest

from syn_api.types import Ok

# Ensure test environment for in-memory adapters
os.environ.setdefault("APP_ENVIRONMENT", "test")


@pytest.fixture(autouse=True)
def _reset_storage():
    """Reset in-memory storage and projections between tests."""
    from syn_adapters.projection_stores import get_projection_store
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    store = get_projection_store()
    if hasattr(store, "_data"):
        store._data.clear()
    if hasattr(store, "_state"):
        store._state.clear()
    yield
    reset_storage()
    reset_projection_manager()


async def test_list_sessions_empty():
    """List sessions when none exist."""
    from syn_api.routes.sessions import list_sessions

    result = await list_sessions()

    assert isinstance(result, Ok)
    assert result.value == []


async def test_start_session():
    """Start a new session."""
    from syn_api.routes.sessions import start_session

    result = await start_session(
        workflow_id="wf-test-123",
        phase_id="phase-1",
        agent_type="claude",
    )

    assert isinstance(result, Ok)
    assert isinstance(result.value, str)
    assert len(result.value) > 0


async def test_start_and_list_sessions():
    """Start a session and verify list returns Ok.

    Note: In test mode, session events go to the SDK event store via
    repository.save() but aren't dispatched to projections (no subscription
    service running). The list query returns Ok but may not contain the
    session. Full round-trip is verified in integration tests.
    """
    from syn_api.routes.sessions import list_sessions, start_session

    start_result = await start_session(
        workflow_id="wf-test-456",
        phase_id="phase-1",
        agent_type="mock",
    )
    assert isinstance(start_result, Ok)

    # Verify list_sessions returns successfully
    list_result = await list_sessions()
    assert isinstance(list_result, Ok)


async def test_complete_session():
    """Start then complete a session."""
    from syn_api.routes.sessions import complete_session, start_session

    start_result = await start_session(
        workflow_id="wf-test-789",
        phase_id="phase-1",
    )
    assert isinstance(start_result, Ok)
    session_id = start_result.value

    # CompleteSessionHandler is currently a stub (pass), so this should not error
    complete_result = await complete_session(session_id)
    assert isinstance(complete_result, Ok)


async def test_get_session_includes_lineage_fields():
    """get_session() must surface parent_session_id/root_session_id (#895).

    Regression test: SessionDetail gained these fields for #895, but the
    SessionDetail(...) construction in get_session() was never updated to
    pass them through, so the field existed and was always None at this
    endpoint despite being correctly populated in list_sessions().
    """
    from syn_api._wiring import get_session_repo, sync_published_events_to_projections
    from syn_api.routes.sessions import get_session
    from syn_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
        AgentSessionAggregate,
    )
    from syn_domain.contexts.agent_sessions.domain.commands.StartSessionCommand import (
        StartSessionCommand,
    )

    repo = get_session_repo()
    session_id = "lineage-test-0001"

    agg = AgentSessionAggregate()
    agg.start_session(
        StartSessionCommand(
            aggregate_id=session_id,
            workflow_id="wf-lineage",
            execution_id="exec-lineage",
            phase_id="phase-1",
            agent_provider="claude",
        )
    )
    await repo.save(agg)
    await sync_published_events_to_projections()

    result = await get_session(session_id)

    assert isinstance(result, Ok)
    # A leader session (no parent) has root_session_id == its own id.
    assert result.value.parent_session_id is None
    assert result.value.root_session_id == session_id


async def test_get_session_running_duration_advances_between_reads():
    """A RUNNING session's duration_seconds must be computed live, not read
    back as the ``None`` Lane 2 leaves it in before completion.

    Regression test for the 2026-09-01 incident (frozen duration misread as
    a hang). A test asserting only ``duration_seconds is not None`` would
    already pass today against a stale value -- so this asserts it ADVANCES
    between two reads of the same still-running session.
    """
    from syn_api._wiring import get_session_repo, sync_published_events_to_projections
    from syn_api.routes.sessions import get_session
    from syn_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
        AgentSessionAggregate,
    )
    from syn_domain.contexts.agent_sessions.domain.commands.StartSessionCommand import (
        StartSessionCommand,
    )

    repo = get_session_repo()
    session_id = "duration-advance-test-0001"

    agg = AgentSessionAggregate()
    agg.start_session(
        StartSessionCommand(
            aggregate_id=session_id,
            workflow_id="wf-duration",
            execution_id="exec-duration",
            phase_id="phase-1",
            agent_provider="claude",
        )
    )
    await repo.save(agg)
    await sync_published_events_to_projections()

    first = await get_session(session_id)
    assert isinstance(first, Ok)
    assert first.value.status == "running"
    first_duration = first.value.duration_seconds
    assert first_duration is not None

    await asyncio.sleep(0.05)

    second = await get_session(session_id)
    assert isinstance(second, Ok)
    second_duration = second.value.duration_seconds
    assert second_duration is not None
    assert second_duration > first_duration


async def test_get_session_last_event_at_advances_on_operation():
    """last_event_at must track the most recent observability event, not
    just session start -- it's the only field that answers "is this session
    alive" for a session that is running but between duration ticks.

    Regression coverage for the hop-drop trap: last_event_at is computed on
    the domain SessionSummary read model, but get_session() constructs a
    SEPARATE SessionDetail response model, so wiring it through only the
    domain layer without also passing it at the route/service boundary would
    leave this field permanently None at this endpoint despite being
    correctly populated in the projection.
    """
    from syn_api._wiring import get_session_repo, sync_published_events_to_projections
    from syn_api.routes.sessions import get_session
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

    repo = get_session_repo()
    session_id = "last-event-at-test-0001"

    agg = AgentSessionAggregate()
    agg.start_session(
        StartSessionCommand(
            aggregate_id=session_id,
            workflow_id="wf-last-event",
            execution_id="exec-last-event",
            phase_id="phase-1",
            agent_provider="claude",
        )
    )
    await repo.save(agg)
    await sync_published_events_to_projections()

    after_start = await get_session(session_id)
    assert isinstance(after_start, Ok)
    last_event_at_after_start = after_start.value.last_event_at
    assert last_event_at_after_start is not None

    await asyncio.sleep(0.05)

    agg.record_operation(
        RecordOperationCommand(
            aggregate_id=session_id,
            operation_type=OperationType.TOOL_EXECUTION_STARTED,
            tool_name="Bash",
            tool_use_id="tool-1",
        )
    )
    await repo.save(agg)
    await sync_published_events_to_projections()

    after_operation = await get_session(session_id)
    assert isinstance(after_operation, Ok)
    last_event_at_after_operation = after_operation.value.last_event_at
    assert last_event_at_after_operation is not None
    assert last_event_at_after_operation > last_event_at_after_start


async def test_list_sessions_surfaces_last_event_at():
    """list_sessions() must not drop last_event_at between the domain read
    model and its own internal SessionSummary DTO.

    syn_api.types.SessionSummary (used by list_sessions()) is a SEPARATE
    Pydantic model from the domain SessionSummary dataclass of the same
    name -- adding a field to one without wiring it through the other is
    exactly the silent hop-drop this test guards against.
    """
    from syn_api._wiring import get_session_repo, sync_published_events_to_projections
    from syn_api.routes.sessions import list_sessions
    from syn_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
        AgentSessionAggregate,
    )
    from syn_domain.contexts.agent_sessions.domain.commands.StartSessionCommand import (
        StartSessionCommand,
    )

    repo = get_session_repo()
    session_id = "list-last-event-at-test-0001"

    agg = AgentSessionAggregate()
    agg.start_session(
        StartSessionCommand(
            aggregate_id=session_id,
            workflow_id="wf-list-last-event",
            execution_id="exec-list-last-event",
            phase_id="phase-1",
            agent_provider="claude",
        )
    )
    await repo.save(agg)
    await sync_published_events_to_projections()

    result = await list_sessions()
    assert isinstance(result, Ok)
    summary = next(s for s in result.value if s.id == session_id)
    assert summary.last_event_at is not None
