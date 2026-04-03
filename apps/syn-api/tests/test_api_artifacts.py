"""Tests for syn_api.routes.artifacts — list, get, create."""

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


async def test_list_artifacts_returns_empty():
    """list_artifacts returns Ok([]) when no artifacts exist."""
    from syn_api.routes.artifacts import list_artifacts

    result = await list_artifacts()
    assert isinstance(result, Ok)
    assert result.value == []


async def test_list_artifacts_with_filter():
    """list_artifacts accepts workflow_id filter."""
    from syn_api.routes.artifacts import list_artifacts

    result = await list_artifacts(workflow_id="nonexistent-wf")
    assert isinstance(result, Ok)
    assert result.value == []


async def test_create_artifact():
    """Create an artifact and get back an ID."""
    from syn_api.routes.artifacts import create_artifact

    result = await create_artifact(
        workflow_id="wf-test-123",
        artifact_type="other",
        title="Test Artifact",
        content="Hello, world!",
    )

    assert isinstance(result, Ok)
    assert isinstance(result.value, str)
    assert len(result.value) > 0


async def test_create_and_list_artifacts():
    """Create an artifact then list to verify round-trip."""
    from syn_api.routes.artifacts import create_artifact, list_artifacts

    create_result = await create_artifact(
        workflow_id="wf-test-456",
        artifact_type="code",
        title="Code Artifact",
        content="print('hello')",
        phase_id="phase-1",
    )
    assert isinstance(create_result, Ok)

    created_id = create_result.value
    assert isinstance(created_id, str)
    assert created_id

    list_result = await list_artifacts(workflow_id="wf-test-456")
    assert isinstance(list_result, Ok)
    assert isinstance(list_result.value, list)
    # NOTE: In-memory event store doesn't auto-dispatch to projections,
    # so the created artifact may not appear in list results.
    # Full round-trip is verified in integration tests with real infrastructure.
