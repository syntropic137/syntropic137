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

    @pytest.mark.anyio
    async def test_uses_result_event_tokens_for_command(self) -> None:
        """Command uses authoritative result-event tokens, not accumulated (ISS-217)."""
        handler = AgentExecutionHandler(controller=None)
        workspace = MagicMock()
        workspace.last_stream_exit_code = 0

        mock_stream_result = StreamResult(
            line_count=10,
            interrupt_requested=False,
            interrupt_reason=None,
            agent_task_result=None,
            total_cost_usd=0.0319,
            result_input_tokens=685,
            result_output_tokens=1961,
            result_cache_creation=5596,
            result_cache_read=144509,
            duration_ms=48000,
            num_turns=7,
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

        # Command must use the result-event totals
        assert result.command.input_tokens == 685
        assert result.command.output_tokens == 1961

    @pytest.mark.anyio
    async def test_session_summary_emitted_after_streaming(self) -> None:
        """record_session_summary is called with CLI result totals (ISS-217)."""
        handler = AgentExecutionHandler(controller=None)
        workspace = MagicMock()
        workspace.last_stream_exit_code = 0

        mock_stream_result = StreamResult(
            line_count=5,
            interrupt_requested=False,
            interrupt_reason=None,
            agent_task_result=None,
            total_cost_usd=0.0319,
            result_input_tokens=685,
            result_output_tokens=1961,
            result_cache_creation=5596,
            result_cache_read=144509,
            duration_ms=48000,
            num_turns=7,
        )

        collector = AsyncMock()

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
            await handler.handle(
                todo=todo,
                workspace=workspace,
                agent_env={},
                claude_cmd=["claude"],
                session_id="sess-1",
                agent_model="claude-haiku",
                timeout_seconds=300,
                collector=collector,
            )

        collector.record_session_summary.assert_called_once_with(
            total_cost_usd=0.0319,
            input_tokens=685,
            output_tokens=1961,
            cache_creation=5596,
            cache_read=144509,
            num_turns=7,
            duration_ms=48000,
        )


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


# =========================================================================
# Extracted helper functions
# =========================================================================


@pytest.mark.unit
class TestDetectExitCode:
    """Tests for _detect_exit_code helper."""

    def test_interrupt_returns_1(self) -> None:
        from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
            _detect_exit_code,
        )
        from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
            TokenAccumulator,
        )

        stream_result = StreamResult(
            line_count=5,
            interrupt_requested=True,
            interrupt_reason="cancel",
            agent_task_result=None,
        )
        workspace = MagicMock()
        assert _detect_exit_code(stream_result, workspace, "p-1", TokenAccumulator()) == 1

    def test_nonzero_stream_exit_code(self) -> None:
        from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
            _detect_exit_code,
        )
        from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
            TokenAccumulator,
        )

        stream_result = StreamResult(
            line_count=5,
            interrupt_requested=False,
            interrupt_reason=None,
            agent_task_result=None,
        )
        workspace = MagicMock()
        workspace.last_stream_exit_code = 42
        assert _detect_exit_code(stream_result, workspace, "p-1", TokenAccumulator()) == 42

    def test_success_returns_0(self) -> None:
        from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
            _detect_exit_code,
        )
        from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
            TokenAccumulator,
        )

        stream_result = StreamResult(
            line_count=10,
            interrupt_requested=False,
            interrupt_reason=None,
            agent_task_result=None,
        )
        workspace = MagicMock()
        workspace.last_stream_exit_code = 0
        tokens = TokenAccumulator()
        tokens.record(100, 50)
        assert _detect_exit_code(stream_result, workspace, "p-1", tokens) == 0


@pytest.mark.unit
class TestBuildAgentEnv:
    """Tests for _build_agent_env helper."""

    def test_returns_env_with_proxy_url(self) -> None:
        from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
            _build_agent_env,
        )

        workspace = MagicMock()
        workspace.proxy_url = "http://envoy:10000"
        env = _build_agent_env(workspace, "sess-1")
        assert env["CLAUDE_SESSION_ID"] == "sess-1"
        assert env["ANTHROPIC_BASE_URL"] == "http://envoy:10000"
        assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "proxy-managed"

    def test_raises_without_proxy(self) -> None:
        from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
            _build_agent_env,
        )

        workspace = MagicMock(spec=[])  # no proxy_url attribute
        with pytest.raises(RuntimeError, match="proxy not available"):
            _build_agent_env(workspace, "sess-1")


# =========================================================================
# WorkspaceProvisionHandler — _generate_workspace_context
# =========================================================================


@pytest.mark.unit
class TestWorkspaceProvisionHandler:
    """Tests for WorkspaceProvisionHandler static helpers and inject behaviour."""

    def test_generate_workspace_context_empty(self) -> None:
        """Empty repos list returns empty string (no inject)."""
        from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
            WorkspaceProvisionHandler,
        )

        assert WorkspaceProvisionHandler._generate_workspace_context([]) == ""

    def test_generate_workspace_context_single_repo(self) -> None:
        """Single repo produces AGENTS.md + CLAUDE.md @-import lines."""
        from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
            WorkspaceProvisionHandler,
        )

        context = WorkspaceProvisionHandler._generate_workspace_context(
            ["https://github.com/org/repo-a"]
        )
        assert "@/workspace/repos/repo-a/AGENTS.md" in context
        assert "@/workspace/repos/repo-a/CLAUDE.md" in context

    def test_generate_workspace_context_multi_repo(self) -> None:
        """Two repos produce four @-import lines (AGENTS + CLAUDE per repo)."""
        from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
            WorkspaceProvisionHandler,
        )

        context = WorkspaceProvisionHandler._generate_workspace_context(
            [
                "https://github.com/org/repo-a",
                "https://github.com/org/repo-b",
            ]
        )
        assert context.count("@/workspace/repos/") == 4
        assert "@/workspace/repos/repo-a/AGENTS.md" in context
        assert "@/workspace/repos/repo-a/CLAUDE.md" in context
        assert "@/workspace/repos/repo-b/AGENTS.md" in context
        assert "@/workspace/repos/repo-b/CLAUDE.md" in context

    def test_generate_workspace_context_agents_before_claude(self) -> None:
        """AGENTS.md @-import appears before CLAUDE.md for each repo."""
        from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
            WorkspaceProvisionHandler,
        )

        context = WorkspaceProvisionHandler._generate_workspace_context(
            ["https://github.com/org/repo-a"]
        )
        agents_pos = context.index("AGENTS.md")
        claude_pos = context.index("CLAUDE.md")
        assert agents_pos < claude_pos

    def test_generate_workspace_context_strips_git_suffix(self) -> None:
        """.git suffix is stripped from repo name."""
        from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
            WorkspaceProvisionHandler,
        )

        context = WorkspaceProvisionHandler._generate_workspace_context(
            ["https://github.com/org/repo-a.git"]
        )
        assert "@/workspace/repos/repo-a/AGENTS.md" in context
        assert ".git" not in context

    def test_generate_workspace_context_ends_with_newline(self) -> None:
        """Generated content ends with a newline."""
        from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
            WorkspaceProvisionHandler,
        )

        context = WorkspaceProvisionHandler._generate_workspace_context(
            ["https://github.com/org/repo-a"]
        )
        assert context.endswith("\n")

    @pytest.mark.anyio
    async def test_handle_injects_both_agents_and_claude_md(self) -> None:
        """handle() injects AGENTS.md and CLAUDE.md with identical content."""
        from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
        from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
            AgentConfiguration,
            ExecutablePhase,
        )
        from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
            WorkspaceProvisionHandler,
        )

        workspace = AsyncMock()
        workspace.proxy_url = "http://envoy:10000"
        workspace.run_setup_phase = AsyncMock(return_value=MagicMock(exit_code=0))
        workspace.inject_files = AsyncMock()
        workspace.id = "ws-test"

        workspace_cm = AsyncMock()
        workspace_cm.__aenter__ = AsyncMock(return_value=workspace)

        workspace_service = MagicMock()
        workspace_service.create_workspace.return_value = workspace_cm

        async def fake_prompt_builder(*_args: object, **_kwargs: object) -> str:
            return "Do the task"

        def fake_command_builder(_phase: object, prompt: str) -> list[str]:
            return ["claude", "--print", prompt]

        handler = WorkspaceProvisionHandler(
            workspace_service=workspace_service,
            prompt_builder=fake_prompt_builder,
            command_builder=fake_command_builder,
        )

        todo = TodoItem(
            execution_id="exec-1",
            action=TodoAction.PROVISION_WORKSPACE,
            phase_id="phase-1",
        )
        phase = ExecutablePhase(
            phase_id="phase-1",
            name="Test Phase",
            order=1,
            description="",
            agent_config=AgentConfiguration(),
            prompt_template="Do the task",
            output_artifact_type="text",
        )

        repos = ["https://github.com/org/repo-a"]

        with patch(
            "syn_adapters.workspace_backends.service.SetupPhaseSecrets"
        ) as MockSecrets:
            mock_secrets_instance = MagicMock()
            mock_secrets_instance.build_setup_script.return_value = "#!/bin/bash\necho ok\n"
            MockSecrets.create = AsyncMock(return_value=mock_secrets_instance)

            result = await handler.handle(
                todo=todo,
                phase=phase,
                workflow_id="wf-1",
                session_id="sess-1",
                repos=repos,
            )

        # inject_files should be called with both AGENTS.md and CLAUDE.md
        inject_calls = workspace.inject_files.call_args_list
        # Find the call that contains AGENTS.md and CLAUDE.md
        context_inject = next(
            c for c in inject_calls
            if any("AGENTS.md" in str(f) or "CLAUDE.md" in str(f) for f in c.args[0])
        )
        files_injected = dict(context_inject.args[0])
        assert "AGENTS.md" in files_injected
        assert "CLAUDE.md" in files_injected
        assert files_injected["AGENTS.md"] == files_injected["CLAUDE.md"], (
            "AGENTS.md and CLAUDE.md must have identical content"
        )
        assert result is not None

    @pytest.mark.anyio
    async def test_handle_no_repos_skips_context_inject(self) -> None:
        """handle() with empty repos does not inject context files."""
        from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
        from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
            AgentConfiguration,
            ExecutablePhase,
        )
        from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
            WorkspaceProvisionHandler,
        )

        workspace = AsyncMock()
        workspace.proxy_url = "http://envoy:10000"
        workspace.run_setup_phase = AsyncMock(return_value=MagicMock(exit_code=0))
        workspace.inject_files = AsyncMock()
        workspace.id = "ws-test"

        workspace_cm = AsyncMock()
        workspace_cm.__aenter__ = AsyncMock(return_value=workspace)

        workspace_service = MagicMock()
        workspace_service.create_workspace.return_value = workspace_cm

        async def fake_prompt_builder(*_args: object, **_kwargs: object) -> str:
            return "Do the task"

        def fake_command_builder(_phase: object, prompt: str) -> list[str]:
            return ["claude", "--print", prompt]

        handler = WorkspaceProvisionHandler(
            workspace_service=workspace_service,
            prompt_builder=fake_prompt_builder,
            command_builder=fake_command_builder,
        )

        todo = TodoItem(
            execution_id="exec-1",
            action=TodoAction.PROVISION_WORKSPACE,
            phase_id="phase-1",
        )
        phase = ExecutablePhase(
            phase_id="phase-1",
            name="Test Phase",
            order=1,
            description="",
            agent_config=AgentConfiguration(),
            prompt_template="Do the task",
            output_artifact_type="text",
        )

        with patch(
            "syn_adapters.workspace_backends.service.SetupPhaseSecrets"
        ) as MockSecrets:
            mock_secrets_instance = MagicMock()
            mock_secrets_instance.build_setup_script.return_value = "#!/bin/bash\necho ok\n"
            MockSecrets.create = AsyncMock(return_value=mock_secrets_instance)

            await handler.handle(
                todo=todo,
                phase=phase,
                workflow_id="wf-1",
                session_id="sess-1",
                repos=[],
            )

        # inject_files should not have been called with context files
        for call in workspace.inject_files.call_args_list:
            for filename, _ in call.args[0]:
                assert filename not in ("AGENTS.md", "CLAUDE.md"), (
                    f"Unexpected context inject for {filename} with empty repos"
                )
