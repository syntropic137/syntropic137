"""Unit tests for infrastructure handlers (ISS-196).

Tests that each handler is independently testable and issues
correct commands back to the aggregate.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_domain.contexts.orchestration._shared.TodoValueObjects import (
    TodoAction,
    TodoItem,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    AgentExecutionCompletedCommand,
    ArtifactsCollectedCommand,
)
from syn_domain.contexts.orchestration.domain.commands.ExecuteWorkflowCommand import (
    ExecuteWorkflowCommand,
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
    async def test_interrupt_does_not_synthesise_exit_code_1(self) -> None:
        """Interrupted execution must NOT synthesise exit_code=1.

        The processor (_handle_run_agent) is responsible for routing interrupt_requested
        to CancelExecutionCommand. _detect_exit_code must only return the actual process
        exit code so the processor can make the cancellation vs failure decision cleanly.
        """
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

        assert result.command.exit_code == 0, (
            "exit_code must reflect workspace state (0), not synthesise 1 for interrupt_requested"
        )
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

    def test_interrupt_does_not_return_1(self) -> None:
        """interrupt_requested must NOT synthesise exit code 1.

        The processor (_handle_cancel_signal) owns the cancellation routing.
        _detect_exit_code must only return the actual process exit code.
        """
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
        workspace.last_stream_exit_code = None
        assert _detect_exit_code(stream_result, workspace, "p-1", TokenAccumulator()) == 0

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
    """Tests for _build_agent_env helper.

    Updated 2026-05-01 (ADR-024 amendment): the helper no longer injects a
    "proxy-managed" placeholder into CLAUDE_CODE_OAUTH_TOKEN. Claude Code CLI
    v2.1.76+ rejects the placeholder at its local format check before any HTTP
    call, so the sidecar substitution pattern is no longer viable. Instead the
    helper reads settings.claude_code_oauth_token (preferred) or
    settings.anthropic_api_key (fallback) and injects the real value, OR
    injects nothing if neither is configured. See ADR-024 2026-05-01 update.
    """

    async def test_returns_session_id_and_proxy_when_no_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With no credentials in settings, env contains session id + proxy url only."""
        from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
            _build_agent_env,
        )
        from syn_shared.settings import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "claude_code_oauth_token", None, raising=False)
        monkeypatch.setattr(settings, "anthropic_api_key", None, raising=False)

        workspace = MagicMock()
        workspace.proxy_url = "http://envoy:10000"
        env = await _build_agent_env(workspace, "sess-1")
        assert env["CLAUDE_SESSION_ID"] == "sess-1"
        assert env["ANTHROPIC_BASE_URL"] == "http://envoy:10000"
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in env
        assert "ANTHROPIC_API_KEY" not in env

    async def test_injects_oauth_token_when_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OAuth token in settings -> injected into agent env."""
        from pydantic import SecretStr

        from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
            _build_agent_env,
        )
        from syn_shared.settings import get_settings

        settings = get_settings()
        monkeypatch.setattr(
            settings,
            "claude_code_oauth_token",
            SecretStr("sk-ant-oat01-real-token"),
            raising=False,
        )
        monkeypatch.setattr(settings, "anthropic_api_key", None, raising=False)

        workspace = MagicMock()
        workspace.proxy_url = "http://envoy:10000"
        env = await _build_agent_env(workspace, "sess-1")
        assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-real-token"
        assert "ANTHROPIC_API_KEY" not in env

    async def test_falls_back_to_api_key_when_oauth_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No OAuth, but API key set -> API key injected as fallback."""
        from pydantic import SecretStr

        from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
            _build_agent_env,
        )
        from syn_shared.settings import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "claude_code_oauth_token", None, raising=False)
        monkeypatch.setattr(
            settings,
            "anthropic_api_key",
            SecretStr("sk-ant-api03-real-key"),
            raising=False,
        )

        workspace = MagicMock()
        workspace.proxy_url = "http://envoy:10000"
        env = await _build_agent_env(workspace, "sess-1")
        assert env["ANTHROPIC_API_KEY"] == "sk-ant-api03-real-key"
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in env

    async def test_oauth_preferred_over_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Both set -> OAuth wins; API key not injected."""
        from pydantic import SecretStr

        from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
            _build_agent_env,
        )
        from syn_shared.settings import get_settings

        settings = get_settings()
        monkeypatch.setattr(
            settings,
            "claude_code_oauth_token",
            SecretStr("sk-ant-oat01-pref"),
            raising=False,
        )
        monkeypatch.setattr(
            settings,
            "anthropic_api_key",
            SecretStr("sk-ant-api-fallback"),
            raising=False,
        )

        workspace = MagicMock()
        workspace.proxy_url = "http://envoy:10000"
        env = await _build_agent_env(workspace, "sess-1")
        assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-pref"
        assert "ANTHROPIC_API_KEY" not in env

    async def test_raises_without_proxy(self) -> None:
        from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
            _build_agent_env,
        )

        workspace = MagicMock()
        workspace.proxy_url = None  # sidecar not running
        with pytest.raises(RuntimeError, match="proxy not available"):
            await _build_agent_env(workspace, "sess-1")


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
        workspace.workspace_id = "ws-test"

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

        with patch("syn_adapters.workspace_backends.service.SetupPhaseSecrets") as MockSecrets:
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
            c
            for c in inject_calls
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
        workspace.workspace_id = "ws-test"

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

        with patch("syn_adapters.workspace_backends.service.SetupPhaseSecrets") as MockSecrets:
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

    @pytest.mark.anyio
    async def test_handle_setup_failure_cleans_up_workspace(self) -> None:
        """When setup phase fails, workspace context manager __aexit__ is called (P0 leak fix)."""
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
        workspace.workspace_id = "ws-test"
        workspace.run_setup_phase = AsyncMock(
            return_value=MagicMock(exit_code=1, stderr="Script error")
        )

        workspace_cm = AsyncMock()
        workspace_cm.__aenter__ = AsyncMock(return_value=workspace)
        workspace_cm.__aexit__ = AsyncMock(return_value=False)

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

        with patch("syn_adapters.workspace_backends.service.SetupPhaseSecrets") as MockSecrets:
            MockSecrets.create = AsyncMock(return_value=MagicMock())
            with pytest.raises(RuntimeError, match="Setup phase failed"):
                await handler.handle(
                    todo=todo,
                    phase=phase,
                    workflow_id="wf-1",
                    session_id="sess-1",
                    repos=[],
                )

        # Container must have been cleaned up despite the failure
        workspace_cm.__aexit__.assert_called_once()


# =========================================================================
# ExecuteWorkflowHandler — _resolve_repos
# =========================================================================


def _make_workflow_stub(
    repository_url: str | None = None,
    repos: list[str] | None = None,
) -> MagicMock:
    """Return a minimal WorkflowTemplateAggregate stub for _resolve_repos tests."""
    wf = MagicMock()
    wf._repository_url = repository_url
    wf.repos = repos or []
    wf.input_declarations = []
    return wf


def _make_cmd(
    inputs: dict[str, str] | None = None,
    repos: list[RepositoryRef] | None = None,
) -> ExecuteWorkflowCommand:
    """Create a minimal ExecuteWorkflowCommand for _resolve_repos tests."""
    return ExecuteWorkflowCommand(
        aggregate_id="wf-test",
        inputs=inputs or {},
        repos=repos or [],
    )


@pytest.mark.unit
class TestResolveRepos:
    """Tests for ExecuteWorkflowHandler._resolve_repos."""

    def test_typed_repos_take_precedence_over_template_fields(self) -> None:
        """Typed RepositoryRef on command takes precedence over template fields (ADR-063)."""
        from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
            ExecuteWorkflowHandler,
        )

        cmd = _make_cmd(repos=[RepositoryRef.from_slug("org/typed-repo")])
        result = ExecuteWorkflowHandler._resolve_repos(
            cmd,
            {},
            _make_workflow_stub(repos=["https://github.com/org/template-repo"]),
        )
        assert result == [RepositoryRef.from_slug("org/typed-repo")]

    def test_typed_multi_repo_resolved(self) -> None:
        """A list of typed RepositoryRefs flows through unchanged in order."""
        from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
            ExecuteWorkflowHandler,
        )

        cmd = _make_cmd(
            repos=[
                RepositoryRef.from_slug("org/repo-a"),
                RepositoryRef.from_slug("org/repo-b"),
            ]
        )
        result = ExecuteWorkflowHandler._resolve_repos(cmd, {}, _make_workflow_stub())
        assert result == [
            RepositoryRef.from_slug("org/repo-a"),
            RepositoryRef.from_slug("org/repo-b"),
        ]

    def test_falls_back_to_template_repos_when_command_repos_empty(self) -> None:
        """Falls back to workflow.repos when command.repos is empty."""
        from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
            ExecuteWorkflowHandler,
        )

        result = ExecuteWorkflowHandler._resolve_repos(
            _make_cmd(),
            {},
            _make_workflow_stub(repos=["https://github.com/org/repo-a"]),
        )
        assert result == [RepositoryRef.from_slug("org/repo-a")]

    def test_falls_back_to_repository_url_when_template_repos_empty(self) -> None:
        """Falls back to template repository_url when both command.repos and workflow.repos are empty."""
        from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
            ExecuteWorkflowHandler,
        )

        result = ExecuteWorkflowHandler._resolve_repos(
            _make_cmd(),
            {},
            _make_workflow_stub(repository_url="https://github.com/org/repo-a"),
        )
        assert result == [RepositoryRef.from_slug("org/repo-a")]

    def test_empty_command_and_no_template_repos_returns_empty(self) -> None:
        """No command repos, no template repos, no repository_url -> empty list."""
        from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
            ExecuteWorkflowHandler,
        )

        result = ExecuteWorkflowHandler._resolve_repos(_make_cmd(), {}, _make_workflow_stub())
        assert result == []

    def test_inputs_repos_without_typed_repos_raises(self) -> None:
        """ADR-063 guard: inputs['repos'] without command.repos is a missed boundary translation."""
        from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
            ExecuteWorkflowHandler,
        )

        with pytest.raises(ValueError, match=r"inputs\[repos\].*command\.repos is empty"):
            ExecuteWorkflowHandler._resolve_repos(
                _make_cmd(),
                {"repos": "https://github.com/org/repo-a"},
                _make_workflow_stub(),
            )

    def test_inputs_repository_without_typed_repos_raises(self) -> None:
        """ADR-063 guard: inputs['repository'] without command.repos is a missed boundary translation."""
        from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
            ExecuteWorkflowHandler,
        )

        with pytest.raises(ValueError, match=r"inputs\[repository\].*command\.repos is empty"):
            ExecuteWorkflowHandler._resolve_repos(
                _make_cmd(),
                {"repository": "syntropic137/syntropic137", "pr_number": "42"},
                _make_workflow_stub(),
            )

    def test_typed_repos_bypass_inputs_guard(self) -> None:
        """When command.repos is set, reserved input keys are ignored (typed wins)."""
        from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
            ExecuteWorkflowHandler,
        )

        cmd = _make_cmd(repos=[RepositoryRef.from_slug("org/typed-repo")])
        result = ExecuteWorkflowHandler._resolve_repos(
            cmd,
            {"repos": "ignored", "repository": "also/ignored"},
            _make_workflow_stub(),
        )
        assert result == [RepositoryRef.from_slug("org/typed-repo")]
