"""Unit tests for infrastructure handlers (ISS-196).

Tests that each handler is independently testable and issues
correct commands back to the aggregate.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_domain.contexts.orchestration._shared.TodoValueObjects import (
    TodoAction,
    TodoItem,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    AgentExecutionCompletedCommand,
    ArtifactsCollectedCommand,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    StreamResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
    AgentExecutionHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.ArtifactCollectionHandler import (
    ArtifactCollectionHandler,
)

# =========================================================================
# AgentExecutionHandler
# =========================================================================


@pytest.mark.unit
class TestAgentExecutionHandler:
    """Tests for AgentExecutionHandler."""

    @pytest.mark.anyio
    async def test_issues_completed_command(self) -> None:
        """Handler returns AgentExecutionCompletedCommand after execution."""
        handler = AgentExecutionHandler(controller=None)

        # Mock workspace
        workspace = MagicMock()
        workspace.last_stream_exit_code = 0

        async def _fake_stream() -> None:
            return  # yields nothing

        # Patch EventStreamProcessor to avoid actual streaming
        mock_stream_result = StreamResult(
            line_count=10,
            interrupt_requested=False,
            interrupt_reason=None,
            agent_task_result=None,
            conversation_lines=["line1"],
        )

        with patch(
            "syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler.EventStreamProcessor"
        ) as MockProcessor:
            mock_instance = AsyncMock()
            mock_instance.process_stream.return_value = mock_stream_result
            MockProcessor.return_value = mock_instance

            todo = TodoItem(
                execution_id="exec-1",
                action=TodoAction.RUN_AGENT,
                phase_id="p-1",
                workspace_id="ws-1",
            )

            result = await handler.handle(
                todo=todo,
                workspace=workspace,
                agent_env={"CLAUDE_SESSION_ID": "sess-1"},
                claude_cmd=["claude", "--model", "haiku"],
                session_id="sess-1",
                agent_model="claude-haiku",
                timeout_seconds=300,
            )

        assert isinstance(result.command, AgentExecutionCompletedCommand)
        assert result.command.aggregate_id == "exec-1"
        assert result.command.phase_id == "p-1"
        assert result.command.session_id == "sess-1"
        assert result.command.exit_code == 0

    @pytest.mark.anyio
    async def test_interrupt_sets_exit_code_1(self) -> None:
        """Interrupted execution sets exit_code to 1."""
        handler = AgentExecutionHandler(controller=None)
        workspace = MagicMock()
        workspace.last_stream_exit_code = 0

        mock_stream_result = StreamResult(
            line_count=5,
            interrupt_requested=True,
            interrupt_reason="User cancelled",
            agent_task_result=None,
        )

        with patch(
            "syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler.EventStreamProcessor"
        ) as MockProcessor:
            mock_instance = AsyncMock()
            mock_instance.process_stream.return_value = mock_stream_result
            MockProcessor.return_value = mock_instance

            todo = TodoItem(
                execution_id="exec-1",
                action=TodoAction.RUN_AGENT,
                phase_id="p-1",
            )

            result = await handler.handle(
                todo=todo,
                workspace=workspace,
                agent_env={},
                claude_cmd=["claude"],
                session_id="sess-1",
                agent_model="claude-haiku",
                timeout_seconds=300,
            )

        assert result.command.exit_code == 1
        assert result.stream_result.interrupt_requested is True


# =========================================================================
# ArtifactCollectionHandler
# =========================================================================


@pytest.mark.unit
class TestArtifactCollectionHandler:
    """Tests for ArtifactCollectionHandler."""

    @pytest.mark.anyio
    async def test_issues_artifacts_collected_command(self) -> None:
        """Handler returns ArtifactsCollectedCommand after collection."""
        from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
            CollectedArtifacts,
        )

        mock_collector = AsyncMock()
        mock_collector.collect_from_workspace.return_value = CollectedArtifacts(
            artifact_ids=["art-1", "art-2"],
            first_content="Result content here",
        )

        handler = ArtifactCollectionHandler(artifact_collector=mock_collector)

        todo = TodoItem(
            execution_id="exec-1",
            action=TodoAction.COLLECT_ARTIFACTS,
            phase_id="p-1",
        )

        result = await handler.handle(
            todo=todo,
            workspace=MagicMock(),
            workflow_id="wf-1",
            session_id="sess-1",
            phase_name="Research",
            output_artifact_type="text",
        )

        assert isinstance(result.command, ArtifactsCollectedCommand)
        assert result.command.aggregate_id == "exec-1"
        assert result.command.phase_id == "p-1"
        assert result.command.artifact_ids == ["art-1", "art-2"]
        assert result.command.first_content_preview == "Result content here"
        assert result.artifact_ids == ["art-1", "art-2"]
        assert result.first_content == "Result content here"

    @pytest.mark.anyio
    async def test_empty_artifacts(self) -> None:
        """Handler handles case with no artifacts collected."""
        from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
            CollectedArtifacts,
        )

        mock_collector = AsyncMock()
        mock_collector.collect_from_workspace.return_value = CollectedArtifacts(
            artifact_ids=[],
            first_content=None,
        )

        handler = ArtifactCollectionHandler(artifact_collector=mock_collector)

        todo = TodoItem(
            execution_id="exec-1",
            action=TodoAction.COLLECT_ARTIFACTS,
            phase_id="p-1",
        )

        result = await handler.handle(
            todo=todo,
            workspace=MagicMock(),
            workflow_id="wf-1",
            session_id="sess-1",
            phase_name="Research",
            output_artifact_type="text",
        )

        assert result.command.artifact_ids == []
        assert result.command.first_content_preview is None


# =========================================================================
# Handler registry
# =========================================================================


@pytest.mark.unit
class TestHandlerRegistry:
    """Tests for the handler registry."""

    def test_registry_has_all_actions(self) -> None:
        """HANDLER_REGISTRY maps all infrastructure actions."""
        from syn_domain.contexts.orchestration.slices.execute_workflow.handlers import (
            HANDLER_REGISTRY,
        )

        assert TodoAction.PROVISION_WORKSPACE in HANDLER_REGISTRY
        assert TodoAction.RUN_AGENT in HANDLER_REGISTRY
        assert TodoAction.COLLECT_ARTIFACTS in HANDLER_REGISTRY

    def test_registry_excludes_domain_actions(self) -> None:
        """COMPLETE_PHASE and COMPLETE_EXECUTION are domain-only (no handler)."""
        from syn_domain.contexts.orchestration.slices.execute_workflow.handlers import (
            HANDLER_REGISTRY,
        )

        assert TodoAction.COMPLETE_PHASE not in HANDLER_REGISTRY
        assert TodoAction.COMPLETE_EXECUTION not in HANDLER_REGISTRY
