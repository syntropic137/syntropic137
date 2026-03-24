"""Tests for syn_api.routes.sessions — start, list, complete cycle.

Uses APP_ENVIRONMENT=test for in-memory adapters.
"""

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
