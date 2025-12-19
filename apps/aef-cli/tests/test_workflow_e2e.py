"""End-to-end tests for the workflow vertical slice.

These tests validate the full path:
CLI Command → Handler → Aggregate → EventStore → Response
"""

from __future__ import annotations

import pytest

from aef_adapters.storage import (
    get_event_publisher,
    get_event_store,
    get_workflow_repository,
    reset_storage,
)
from aef_domain.contexts.workflows._shared.value_objects import (
    PhaseDefinition,
    WorkflowClassification,
    WorkflowType,
)
from aef_domain.contexts.workflows.create_workflow.CreateWorkflowCommand import (
    CreateWorkflowCommand,
)
from aef_domain.contexts.workflows.create_workflow.CreateWorkflowHandler import (
    CreateWorkflowHandler,
)


@pytest.fixture(autouse=True)
def clean_storage() -> None:
    """Reset storage before each test."""
    reset_storage()


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_create_workflow_e2e() -> None:
    """Test the full path: command → handler → aggregate → event store."""
    # Arrange
    repository = get_workflow_repository()
    publisher = get_event_publisher()
    handler = CreateWorkflowHandler(repository=repository, event_publisher=publisher)

    initial_phase = PhaseDefinition(
        phase_id="phase-1",
        name="Research Phase",
        order=1,
        description="Initial research phase",
    )

    command = CreateWorkflowCommand(
        aggregate_id="test-workflow-123",
        name="E2E Test Workflow",
        description="Testing the tracer bullet",
        workflow_type=WorkflowType.RESEARCH,
        classification=WorkflowClassification.STANDARD,
        repository_url="https://github.com/test/repo",
        repository_ref="main",
        phases=[initial_phase],
    )

    # Act
    workflow_id = await handler.handle(command)

    # Assert - workflow created
    assert workflow_id == "test-workflow-123"

    # Assert - event stored
    event_store = get_event_store()
    stored_events = event_store.get_events("test-workflow-123")
    assert len(stored_events) == 1
    assert stored_events[0].event_type == "WorkflowCreated"
    assert stored_events[0].event_data["name"] == "E2E Test Workflow"

    # Assert - event published
    published = publisher.get_published_events()
    assert len(published) == 1


@pytest.mark.asyncio
async def test_retrieve_workflow_e2e() -> None:
    """Test full round-trip: create → store → retrieve."""
    # Arrange - create workflow
    repository = get_workflow_repository()
    publisher = get_event_publisher()
    handler = CreateWorkflowHandler(repository=repository, event_publisher=publisher)

    phase = PhaseDefinition(
        phase_id="p1",
        name="Phase 1",
        order=1,
    )

    command = CreateWorkflowCommand(
        aggregate_id="roundtrip-workflow",
        name="Round Trip Test",
        workflow_type=WorkflowType.PLANNING,
        classification=WorkflowClassification.SIMPLE,
        repository_url="https://github.com/test/repo",
        phases=[phase],
    )

    await handler.handle(command)

    # Act - retrieve workflow
    workflow = await repository.get_by_id("roundtrip-workflow")

    # Assert
    assert workflow is not None
    assert workflow.id == "roundtrip-workflow"
    assert workflow.name == "Round Trip Test"
    assert workflow.status.value == "pending"
    assert len(workflow.phases) == 1


@pytest.mark.asyncio
async def test_create_multiple_workflows_e2e() -> None:
    """Test creating multiple workflows."""
    repository = get_workflow_repository()
    publisher = get_event_publisher()
    handler = CreateWorkflowHandler(repository=repository, event_publisher=publisher)

    phase = PhaseDefinition(phase_id="p1", name="Phase", order=1)

    # Create 3 workflows
    for i in range(3):
        command = CreateWorkflowCommand(
            aggregate_id=f"workflow-{i}",
            name=f"Workflow {i}",
            workflow_type=WorkflowType.CUSTOM,
            classification=WorkflowClassification.STANDARD,
            repository_url="https://github.com/test/repo",
            phases=[phase],
        )
        await handler.handle(command)

    # Assert - all events stored
    event_store = get_event_store()
    all_events = event_store.get_all_events()
    assert len(all_events) == 3

    # Assert - each workflow retrievable
    for i in range(3):
        workflow = await repository.get_by_id(f"workflow-{i}")
        assert workflow is not None
        assert workflow.name == f"Workflow {i}"
