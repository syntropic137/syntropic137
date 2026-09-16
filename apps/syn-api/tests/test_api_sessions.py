"""Tests for syn_api.routes.sessions — start, list, complete cycle.

Uses APP_ENVIRONMENT=test for in-memory adapters.
"""

import asyncio
import os

import pytest

from syn_api.types import Ok

# CI runs `pytest -m unit`; an unmarked module collects zero tests and the
# gate goes green having run none of them (#1065).
pytestmark = pytest.mark.unit


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
    assert result.value.rows == []
    assert result.value.total == 0
    assert result.value.status_counts == {}


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
    """Start then complete a session, and read the completion back (#1034).

    ``complete_session()`` returned Ok while CompleteSessionHandler's body
    was ``pass``, so asserting Ok alone passed against a handler that wrote
    nothing. The session's status at the read path is what distinguishes
    the two.
    """
    from syn_api._wiring import sync_published_events_to_projections
    from syn_api.routes.sessions import complete_session, get_session, start_session

    start_result = await start_session(
        workflow_id="wf-test-789",
        phase_id="phase-1",
    )
    assert isinstance(start_result, Ok)
    session_id = start_result.value

    before = await get_session(session_id)
    assert isinstance(before, Ok)
    assert before.value.status == "running"

    complete_result = await complete_session(session_id)
    assert isinstance(complete_result, Ok)
    await sync_published_events_to_projections()

    after = await get_session(session_id)
    assert isinstance(after, Ok)
    assert after.value.status == "completed"
    assert after.value.completed_at is not None


async def test_recorded_operation_reaches_the_session_read_path():
    """An operation recorded through RecordOperationHandler must be visible
    to the API that serves session detail (#1034).

    The handler was a no-op, so nothing it was handed ever reached the event
    store, the projection, or this endpoint. 4321 is deliberately a number
    no other writer in this system produces: no default, no sum of defaults,
    and the only Lane 1 token writer for a session is the operation stream.
    """
    from syn_api._wiring import get_session_repo, sync_published_events_to_projections
    from syn_api.routes.sessions import get_session, start_session
    from syn_domain.contexts.agent_sessions import (
        RecordOperationCommand,
        RecordOperationHandler,
    )
    from syn_domain.contexts.agent_sessions._shared.value_objects import OperationType

    start_result = await start_session(workflow_id="wf-record-op", phase_id="phase-1")
    assert isinstance(start_result, Ok)
    session_id = start_result.value

    before = await get_session(session_id)
    assert isinstance(before, Ok)
    assert before.value.total_tokens == 0

    await RecordOperationHandler(repository=get_session_repo()).handle(
        RecordOperationCommand(
            aggregate_id=session_id,
            operation_type=OperationType.TOOL_EXECUTION_COMPLETED,
            tool_name="Bash",
            tool_use_id="toolu_record_op_1034",
            tool_output="ran",
            input_tokens=4000,
            output_tokens=321,
            total_tokens=4321,
        )
    )
    await sync_published_events_to_projections()

    after = await get_session(session_id)
    assert isinstance(after, Ok)
    assert after.value.total_tokens == 4321


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


async def test_session_detail_operations_come_only_from_the_lane2_timeline():
    """``operations`` has exactly one source, and it is the Lane 2 timeline (#1034).

    SessionSummary used to carry an operations list of its own that nothing
    read. Recording a Lane 1 operation here and standing in for Lane 2 with a
    single known row is what tells the two apart: if any Lane 1 copy were
    still merged in, this session would report two operations, and the extra
    one would be the totals roll-up the issue calls synthetic.
    """
    from datetime import UTC, datetime

    from syn_adapters.projections.manager import get_projection_manager
    from syn_adapters.projections.session_tools import ToolOperation
    from syn_api._wiring import get_session_repo, sync_published_events_to_projections
    from syn_api.routes.sessions import get_session, start_session
    from syn_domain.contexts.agent_sessions import (
        RecordOperationCommand,
        RecordOperationHandler,
    )
    from syn_domain.contexts.agent_sessions._shared.value_objects import OperationType

    start_result = await start_session(workflow_id="wf-one-lane", phase_id="phase-1")
    assert isinstance(start_result, Ok)
    session_id = start_result.value

    await RecordOperationHandler(repository=get_session_repo()).handle(
        RecordOperationCommand(
            aggregate_id=session_id,
            operation_type=OperationType.MESSAGE_RESPONSE,
            input_tokens=4000,
            output_tokens=321,
            total_tokens=4321,
        )
    )
    await sync_published_events_to_projections()

    class _StandInLane2:
        async def get(self, _session_id: str) -> list[ToolOperation]:
            return [
                ToolOperation(
                    observation_id="obs-lane2-1034",
                    tool_name="Bash",
                    tool_use_id="toolu_lane2_1034",
                    operation_type="tool_execution_completed",
                    timestamp=datetime.now(UTC),
                    success=True,
                    input_preview="echo lane2",
                    output_preview="lane2",
                    duration_ms=12,
                )
            ]

    manager = get_projection_manager()
    manager._ensure_initialized()
    manager._projections["session_tools"] = _StandInLane2()

    detail = await get_session(session_id)
    assert isinstance(detail, Ok)
    assert [op.tool_use_id for op in detail.value.operations] == ["toolu_lane2_1034"]
    # The Lane 1 operation is still real - it is where the tokens came from.
    assert detail.value.total_tokens == 4321


async def test_the_production_completion_path_reaches_the_session_read_path():
    """The caller a real phase execution uses, end to end (#1034).

    ``RecordOperationHandler`` was reachable only from tests. This drives
    ``SessionLifecycleManager.complete_success`` - what WorkflowExecution
    actually calls when a phase finishes - and asserts at the endpoint that
    serves session detail. 4321/4000/321 is a split no default or sum of
    defaults produces.
    """
    from syn_api._wiring import get_session_repo, sync_published_events_to_projections
    from syn_api.routes.sessions import get_session, start_session
    from syn_domain.contexts.orchestration.slices.execute_workflow.SessionLifecycleManager import (
        SessionLifecycleManager,
    )

    start_result = await start_session(workflow_id="wf-prod-path", phase_id="phase-1")
    assert isinstance(start_result, Ok)
    session_id = start_result.value

    repo = get_session_repo()
    manager = SessionLifecycleManager(
        repository=repo,
        session_id=session_id,
        workflow_id="wf-prod-path",
        execution_id="exec-prod-path",
        phase_id="phase-1",
        agent_provider="claude",
        agent_model="claude-sonnet-4-20250514",
    )
    manager._session = await repo.get_by_id(session_id)

    await manager.complete_success(
        input_tokens=4000,
        output_tokens=321,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        total_tokens=4321,
        duration_seconds=1.5,
        source="test-1034",
    )
    await sync_published_events_to_projections()

    detail = await get_session(session_id)
    assert isinstance(detail, Ok)
    assert detail.value.status == "completed"
    assert detail.value.total_tokens == 4321
    assert detail.value.input_tokens == 4000
    assert detail.value.output_tokens == 321
