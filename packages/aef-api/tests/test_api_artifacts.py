"""Tests for aef_api.v1.artifacts — list, get, create."""

from aef_api.types import Ok


async def test_list_artifacts_returns_empty():
    """list_artifacts returns Ok([]) when no artifacts exist."""
    from aef_api.v1.artifacts import list_artifacts

    result = await list_artifacts()
    assert isinstance(result, Ok)
    assert result.value == []


async def test_list_artifacts_with_filter():
    """list_artifacts accepts workflow_id filter."""
    from aef_api.v1.artifacts import list_artifacts

    result = await list_artifacts(workflow_id="nonexistent-wf")
    assert isinstance(result, Ok)
    assert result.value == []
