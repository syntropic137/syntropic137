"""Tests for syn_api.routes.sessions — start, list, complete cycle.

Uses APP_ENVIRONMENT=test for in-memory adapters.
"""

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
