"""Tests for unified WorkflowExecutor.

These tests verify that WorkflowExecutor:
1. REQUIRES ObservabilityPort (Poka-Yoke)
2. Records observations via ObservabilityPort
3. Streams ExecutionEvent correctly
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

# Set test environment before importing NullObservability
os.environ["AEF_ENVIRONMENT"] = "test"

from agentic_observability import NullObservability


@pytest.fixture
def observability():
    """Create NullObservability for testing."""
    return NullObservability()


@pytest.fixture
def mock_agent():
    """Create a mock agent that implements AgenticProtocol."""
    agent = MagicMock()
    agent.is_available = True
    agent.execute = AsyncMock(return_value=iter([]))  # Empty iterator
    return agent


@pytest.fixture
def mock_agent_factory(mock_agent):
    """Create a factory that returns the mock agent."""
    return lambda _provider: mock_agent


@pytest.fixture
def mock_workspace_service():
    """Create a mock workspace service."""
    service = MagicMock()
    return service


@dataclass
class MockPhase:
    """Mock workflow phase for testing."""

    phase_id: str = "phase-1"
    name: str = "Test Phase"
    order: int = 1
    description: str | None = "Test phase description"
    prompt_template: str = "Do the thing with {{input}}"
    allowed_tools: frozenset[str] = frozenset({"Bash", "Read"})
    output_artifact_type: str = "text"
    timeout_seconds: int = 300


@dataclass
class MockWorkflow:
    """Mock workflow definition for testing."""

    workflow_id: str = "workflow-123"
    name: str = "Test Workflow"
    phases: list = None

    def __post_init__(self):
        if self.phases is None:
            self.phases = [MockPhase()]


class TestWorkflowExecutorRequiresObservability:
    """Tests verifying observability is REQUIRED (Poka-Yoke)."""

    def test_raises_if_observability_is_none(self, mock_agent_factory, mock_workspace_service):
        """WorkflowExecutor should raise if observability is None."""
        from aef_adapters.orchestration.workflow_executor import WorkflowExecutor

        with pytest.raises(TypeError) as exc_info:
            WorkflowExecutor(
                observability=None,  # type: ignore
                agent_factory=mock_agent_factory,
                workspace_service=mock_workspace_service,
            )

        assert "requires observability" in str(exc_info.value)

    def test_raises_if_observability_wrong_type(self, mock_agent_factory, mock_workspace_service):
        """WorkflowExecutor should raise if observability is wrong type."""
        from aef_adapters.orchestration.workflow_executor import WorkflowExecutor

        with pytest.raises(TypeError) as exc_info:
            WorkflowExecutor(
                observability="not-an-observability",  # type: ignore
                agent_factory=mock_agent_factory,
                workspace_service=mock_workspace_service,
            )

        assert "ObservabilityPort" in str(exc_info.value)

    def test_accepts_valid_observability(
        self, observability, mock_agent_factory, mock_workspace_service
    ):
        """WorkflowExecutor should accept valid ObservabilityPort."""
        from aef_adapters.orchestration.workflow_executor import WorkflowExecutor

        executor = WorkflowExecutor(
            observability=observability,
            agent_factory=mock_agent_factory,
            workspace_service=mock_workspace_service,
        )

        assert executor is not None


class TestCreateWorkflowExecutorFactory:
    """Tests for the create_workflow_executor factory."""

    def test_raises_without_workspace_service(self, observability, mock_agent_factory):
        """Factory should raise if workspace_service is not provided."""
        from aef_adapters.orchestration.factory import create_workflow_executor

        with pytest.raises(ValueError) as exc_info:
            create_workflow_executor(
                agent_factory=mock_agent_factory,
                observability=observability,
                workspace_service=None,
            )

        assert "workspace_service is required" in str(exc_info.value)

    def test_uses_provided_observability(
        self, observability, mock_agent_factory, mock_workspace_service
    ):
        """Factory should use provided observability."""
        from aef_adapters.orchestration.factory import create_workflow_executor

        executor = create_workflow_executor(
            agent_factory=mock_agent_factory,
            workspace_service=mock_workspace_service,
            observability=observability,
        )

        assert executor._observability is observability

    def test_uses_default_agent_factory(self, observability, mock_workspace_service):
        """Factory should use default agent factory if not provided."""
        from aef_adapters.orchestration.factory import create_workflow_executor

        executor = create_workflow_executor(
            workspace_service=mock_workspace_service,
            observability=observability,
        )

        # Should have created executor with default factory
        assert executor._agent_factory is not None
