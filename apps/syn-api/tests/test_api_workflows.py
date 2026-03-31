"""Tests for syn_api.routes.workflows — create, list, get cycle.

Uses APP_ENVIRONMENT=test for in-memory adapters.
"""

import os

import pytest

from syn_api.types import Err, Ok

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
    # Reset the projection store data
    store = get_projection_store()
    if hasattr(store, "_data"):
        store._data.clear()
    if hasattr(store, "_state"):
        store._state.clear()
    yield
    reset_storage()
    reset_projection_manager()


async def test_create_workflow():
    """Create a workflow and get back an ID."""
    from syn_api.routes.workflows import create_workflow

    result = await create_workflow(
        name="Test Research Workflow",
        workflow_type="research",
        description="A test workflow",
    )

    assert isinstance(result, Ok)
    assert isinstance(result.value, str)
    assert len(result.value) > 0


async def test_list_workflows_empty():
    """List workflows when none exist."""
    from syn_api.routes.workflows import list_workflows

    result = await list_workflows()

    assert isinstance(result, Ok)
    assert result.value == []


async def test_create_and_list_workflows():
    """Create a workflow then list it."""
    from syn_api.routes.workflows import create_workflow, list_workflows

    create_result = await create_workflow(
        name="Listed Workflow",
        workflow_type="custom",
    )
    assert isinstance(create_result, Ok)

    list_result = await list_workflows()
    assert isinstance(list_result, Ok)
    assert len(list_result.value) == 1
    assert list_result.value[0].name == "Listed Workflow"
    assert list_result.value[0].workflow_type == "custom"


async def test_create_and_get_workflow():
    """Create a workflow then get its details."""
    from syn_api.routes.workflows import create_workflow, get_workflow

    create_result = await create_workflow(
        name="Detail Workflow",
        workflow_type="implementation",
        description="Test getting details",
    )
    assert isinstance(create_result, Ok)
    workflow_id = create_result.value

    get_result = await get_workflow(workflow_id)
    assert isinstance(get_result, Ok)
    assert get_result.value.id == workflow_id
    assert get_result.value.name == "Detail Workflow"


async def test_get_workflow_not_found():
    """Get a workflow that doesn't exist."""
    from syn_api.routes.workflows import get_workflow

    result = await get_workflow("nonexistent-id")
    assert isinstance(result, Err)


async def test_create_workflow_with_phases():
    """Create a workflow with custom phases."""
    from syn_api.routes.workflows import create_workflow

    result = await create_workflow(
        name="Multi-Phase Workflow",
        workflow_type="implementation",
        phases=[
            {"name": "Research", "order": 1, "description": "Research phase"},
            {"name": "Implementation", "order": 2, "description": "Code it"},
            {"name": "Review", "order": 3, "description": "Review code"},
        ],
    )
    assert isinstance(result, Ok)


async def test_list_workflows_with_filter():
    """Create workflows of different types and filter."""
    from syn_api.routes.workflows import create_workflow, list_workflows

    await create_workflow(name="Research 1", workflow_type="research")
    await create_workflow(name="Custom 1", workflow_type="custom")

    result = await list_workflows(workflow_type="research")
    assert isinstance(result, Ok)
    assert len(result.value) == 1
    assert result.value[0].name == "Research 1"


async def test_list_executions_empty():
    """List executions when none exist."""
    from syn_api.routes.executions import list_ as list_executions

    result = await list_executions()
    assert isinstance(result, Ok)
    assert result.value == []


async def test_validate_yaml_valid(tmp_path):
    """Validate a valid workflow YAML file."""
    from syn_api.routes.workflows import validate_yaml

    yaml_content = """\
id: test-workflow
name: Test Workflow
type: custom
phases:
  - id: phase-1
    name: Research
    order: 1
    description: Research phase
    agent_type: claude
"""
    yaml_file = tmp_path / "valid.yaml"
    yaml_file.write_text(yaml_content)

    result = await validate_yaml(str(yaml_file))
    assert isinstance(result, Ok)
    assert result.value.valid is True
    assert result.value.name == "Test Workflow"
    assert result.value.phase_count == 1


async def test_validate_yaml_invalid(tmp_path):
    """Validate an invalid workflow YAML file."""
    from syn_api.routes.workflows import validate_yaml

    yaml_content = """\
name: Missing Required Fields
"""
    yaml_file = tmp_path / "invalid.yaml"
    yaml_file.write_text(yaml_content)

    result = await validate_yaml(str(yaml_file))
    assert isinstance(result, Ok)
    assert result.value.valid is False
    assert len(result.value.errors) > 0


async def test_validate_yaml_file_not_found():
    """Validate a non-existent YAML file."""
    from syn_api.routes.workflows import validate_yaml

    result = await validate_yaml("/nonexistent/path/workflow.yaml")
    assert isinstance(result, Err)


# === Delete (archive) workflow tests ===


async def test_delete_workflow():
    """Create a workflow then delete it."""
    from syn_api.routes.workflows import create_workflow, delete_workflow

    create_result = await create_workflow(name="Deletable Workflow")
    assert isinstance(create_result, Ok)
    workflow_id = create_result.value

    delete_result = await delete_workflow(workflow_id)
    assert isinstance(delete_result, Ok)


async def test_delete_workflow_not_found():
    """Delete a workflow that doesn't exist."""
    from syn_api.routes.workflows import delete_workflow

    result = await delete_workflow("nonexistent-id")
    assert isinstance(result, Err)


async def test_delete_workflow_already_archived():
    """Deleting an already-archived workflow returns an error."""
    from syn_api.routes.workflows import create_workflow, delete_workflow

    create_result = await create_workflow(name="Archive Twice")
    assert isinstance(create_result, Ok)
    workflow_id = create_result.value

    first = await delete_workflow(workflow_id)
    assert isinstance(first, Ok)

    second = await delete_workflow(workflow_id)
    assert isinstance(second, Err)
    assert second.error.value == "already_archived"


async def test_list_excludes_archived_by_default():
    """Archived workflows should not appear in the default list."""
    from syn_api.routes.workflows import create_workflow, delete_workflow, list_workflows

    create_result = await create_workflow(name="Soon Archived")
    assert isinstance(create_result, Ok)
    workflow_id = create_result.value

    await delete_workflow(workflow_id)

    list_result = await list_workflows()
    assert isinstance(list_result, Ok)
    assert len(list_result.value) == 0


async def test_list_includes_archived():
    """include_archived=True should return archived workflows."""
    from syn_api.routes.workflows import create_workflow, delete_workflow, list_workflows

    create_result = await create_workflow(name="Archived But Visible")
    assert isinstance(create_result, Ok)
    workflow_id = create_result.value

    await delete_workflow(workflow_id)

    list_result = await list_workflows(include_archived=True)
    assert isinstance(list_result, Ok)
    assert len(list_result.value) == 1
    assert list_result.value[0].is_archived is True


async def test_get_workflow_still_returns_archived():
    """Getting an archived workflow by ID should still work."""
    from syn_api.routes.workflows import create_workflow, delete_workflow, get_workflow

    create_result = await create_workflow(name="Archived Detail")
    assert isinstance(create_result, Ok)
    workflow_id = create_result.value

    await delete_workflow(workflow_id)

    get_result = await get_workflow(workflow_id)
    assert isinstance(get_result, Ok)
    assert get_result.value.id == workflow_id
