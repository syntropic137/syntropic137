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
from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    MISSING_TERMINAL_TURN_REASON,
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
from syn_shared.agents import AgentProvider

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

    @pytest.mark.anyio
    async def test_codex_runner_uses_codex_stream_processor_only(self) -> None:
        """Codex runner selects its parser and preserves the existing stream call."""
        handler = AgentExecutionHandler(controller=None)
        workspace = MagicMock()
        workspace.last_stream_exit_code = 0
        collector = AsyncMock()
        stream_result = StreamResult(
            line_count=3,
            interrupt_requested=False,
            interrupt_reason=None,
            agent_task_result=None,
            result_input_tokens=12,
            result_output_tokens=7,
        )

        with (
            patch(
                "syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler.CodexStreamProcessor"
            ) as mock_codex_processor,
            patch(
                "syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler.EventStreamProcessor"
            ) as mock_claude_processor,
        ):
            mock_codex_processor.return_value.process_stream = AsyncMock(return_value=stream_result)
            result = await handler.handle(
                todo=TodoItem(
                    execution_id="exec-1",
                    action=TodoAction.RUN_AGENT,
                    phase_id="p-1",
                ),
                workspace=workspace,
                agent_env={"CODEX_HOME": "/home/agent/.codex"},
                claude_cmd=["codex", "exec", "--json", "do work"],
                session_id="sess-1",
                agent_model="gpt-5.6",
                timeout_seconds=300,
                collector=collector,
                runner="codex",
            )

        mock_codex_processor.assert_called_once()
        mock_claude_processor.assert_not_called()
        workspace.stream.assert_called_once_with(
            ["codex", "exec", "--json", "do work"],
            timeout_seconds=300,
            environment={"CODEX_HOME": "/home/agent/.codex"},
        )
        assert result.command.input_tokens == 12
        assert result.command.output_tokens == 7

    @pytest.mark.anyio
    async def test_broken_codex_stream_forces_nonzero_exit(self) -> None:
        """Parser-level stream failure overrides a clean process exit for Codex."""
        handler = AgentExecutionHandler(controller=None)
        workspace = MagicMock()
        workspace.last_stream_exit_code = 0
        workspace.collect_files = AsyncMock(return_value=[])
        collector = AsyncMock()
        stream_result = StreamResult(
            line_count=1,
            interrupt_requested=False,
            interrupt_reason=None,
            agent_task_result=None,
            error_reason=MISSING_TERMINAL_TURN_REASON,
        )

        with patch(
            "syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler.CodexStreamProcessor"
        ) as mock_processor:
            mock_processor.return_value.process_stream = AsyncMock(return_value=stream_result)
            result = await handler.handle(
                todo=TodoItem(
                    execution_id="exec-1",
                    action=TodoAction.RUN_AGENT,
                    phase_id="p-1",
                ),
                workspace=workspace,
                agent_env={},
                claude_cmd=["codex", "exec", "--json", "do work"],
                session_id="sess-1",
                agent_model="gpt-5.6",
                timeout_seconds=300,
                collector=collector,
                runner="codex",
            )

        assert result.command.exit_code == 1

    async def _run_broken_codex_stream(
        self,
        *,
        error_reason: str,
        collect_files: AsyncMock,
    ) -> int:
        """Drive a codex phase whose stream carried `error_reason`; return the phase exit code."""
        handler = AgentExecutionHandler(controller=None)
        workspace = MagicMock()
        workspace.last_stream_exit_code = 0
        workspace.collect_files = collect_files
        stream_result = StreamResult(
            line_count=43,
            interrupt_requested=False,
            interrupt_reason=None,
            agent_task_result=None,
            error_reason=error_reason,
        )
        with patch(
            "syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler.CodexStreamProcessor"
        ) as mock_processor:
            mock_processor.return_value.process_stream = AsyncMock(return_value=stream_result)
            result = await handler.handle(
                todo=TodoItem(
                    execution_id="exec-1",
                    action=TodoAction.RUN_AGENT,
                    phase_id="verify",
                ),
                workspace=workspace,
                agent_env={},
                claude_cmd=["codex", "exec", "--json", "review"],
                session_id="sess-1",
                agent_model="gpt-5.6",
                timeout_seconds=300,
                collector=AsyncMock(),
                runner="codex",
            )
        return result.command.exit_code

    @pytest.mark.anyio
    async def test_missing_terminal_turn_completes_when_deliverable_exists(self) -> None:
        """A finished review is not thrown away for a missing usage event (#1111).

        This is the exact production shape: the codex stream ran 43 lines, wrote
        artifacts/output/deliverable.md, and then stopped before turn.completed.
        """
        exit_code = await self._run_broken_codex_stream(
            error_reason=MISSING_TERMINAL_TURN_REASON,
            collect_files=AsyncMock(
                return_value=[("artifacts/output/deliverable.md", b"## Verdict\nBlockers found.")]
            ),
        )
        assert exit_code == 0

    @pytest.mark.anyio
    async def test_missing_terminal_turn_fails_when_output_is_empty(self) -> None:
        """An empty file is not a deliverable - the phase produced nothing."""
        exit_code = await self._run_broken_codex_stream(
            error_reason=MISSING_TERMINAL_TURN_REASON,
            collect_files=AsyncMock(return_value=[("artifacts/output/deliverable.md", b"")]),
        )
        assert exit_code == 1

    @pytest.mark.anyio
    async def test_a_reported_turn_failure_still_fails_even_with_a_deliverable(self) -> None:
        """A stream that SAID it failed must not be read as one that merely stopped.

        This is the composition the cross-model review of #1112 found. The
        completion path keys on the missing-terminal-turn reason being EXACTLY
        the generic one; a genuine `turn.failed` carries its own reason (#1116),
        so it is excluded. Before that reason existed, every reported failure
        collapsed into the generic message and this deliverable would have
        completed a run the stream had explicitly failed.

        The two changes therefore depend on each other, and nothing in the type
        system says so - which is precisely why this test exists rather than a
        comment.
        """
        exit_code = await self._run_broken_codex_stream(
            error_reason=(
                "codex reported: This content was flagged for possible cybersecurity risk."
            ),
            collect_files=AsyncMock(
                return_value=[("artifacts/output/deliverable.md", b"a partial review")]
            ),
        )
        assert exit_code == 1

    @pytest.mark.anyio
    async def test_auth_fault_still_fails_even_with_a_deliverable(self) -> None:
        """#891 stays closed: a login failure fails the phase whatever is on disk.

        A stale deliverable left by an earlier phase must never be able to
        certify a run whose agent never authenticated.
        """
        exit_code = await self._run_broken_codex_stream(
            error_reason="ERROR codex_login::auth::manager: Failed to refresh token: 401",
            collect_files=AsyncMock(
                return_value=[("artifacts/output/deliverable.md", b"stale content")]
            ),
        )
        assert exit_code == 1

    @pytest.mark.anyio
    async def test_unreadable_workspace_fails_closed(self) -> None:
        """If the deliverable check cannot run, the phase fails as it did before."""
        exit_code = await self._run_broken_codex_stream(
            error_reason=MISSING_TERMINAL_TURN_REASON,
            collect_files=AsyncMock(side_effect=RuntimeError("workspace is gone")),
        )
        assert exit_code == 1

    @pytest.mark.anyio
    async def test_clean_codex_stream_keeps_zero_exit_and_one_summary(self) -> None:
        """Codex processor owns the sole session summary emission."""
        handler = AgentExecutionHandler(controller=None)
        workspace = MagicMock()
        workspace.last_stream_exit_code = 0
        collector = AsyncMock()
        stream_result = StreamResult(
            line_count=3,
            interrupt_requested=False,
            interrupt_reason=None,
            agent_task_result=None,
            result_input_tokens=12,
            result_output_tokens=7,
        )

        async def process_stream(*_args: object) -> StreamResult:
            await collector.record_session_summary(
                total_cost_usd=0.01,
                input_tokens=12,
                output_tokens=7,
                cache_creation=0,
                cache_read=0,
                num_turns=1,
                duration_ms=25,
                agent_id=None,
            )
            return stream_result

        with patch(
            "syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler.CodexStreamProcessor"
        ) as mock_processor:
            mock_processor.return_value.process_stream = process_stream
            result = await handler.handle(
                todo=TodoItem(
                    execution_id="exec-1",
                    action=TodoAction.RUN_AGENT,
                    phase_id="p-1",
                ),
                workspace=workspace,
                agent_env={},
                claude_cmd=["codex", "exec", "--json", "do work"],
                session_id="sess-1",
                agent_model="gpt-5.6",
                timeout_seconds=300,
                collector=collector,
                runner="codex",
            )

        assert result.command.exit_code == 0
        collector.record_session_summary.assert_awaited_once()


# =========================================================================
# ArtifactCollectionHandler
# =========================================================================


@pytest.mark.unit
class TestArtifactCollectionHandler:
    """Tests for ArtifactCollectionHandler."""

    @pytest.mark.anyio
    async def test_issues_artifacts_collected_command(self) -> None:
        """Handler returns ArtifactsCollectedCommand after collection."""
        from syn_domain.contexts.artifacts import PhaseOutputFile
        from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
            CollectedArtifacts,
        )

        files = [
            PhaseOutputFile(source_path="artifacts/output/a.md", content="Result content here"),
            PhaseOutputFile(source_path="artifacts/output/b.yaml", content="b: 1"),
        ]
        mock_collector = AsyncMock()
        mock_collector.collect_from_workspace.return_value = CollectedArtifacts(
            artifact_ids=["art-1", "art-2"],
            first_content="Result content here",
            files=files,
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
        # #988: the whole output tree must reach the caller, not just the
        # first file's content. Dropping it here undoes the fix upstream of
        # every injection assertion.
        assert result.files == files

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
        """With no credentials in settings, env contains session id + proxy url only.

        We intentionally do NOT fail-fast here — multiple smoke tests exercise
        the processor loop without configured credentials. A separate startup
        check is the right place to enforce credential presence (tracked
        separately).
        """
        from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
            _build_agent_env,
        )
        from syn_shared.settings import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "claude_code_oauth_token", None, raising=False)
        monkeypatch.setattr(settings, "anthropic_api_key", None, raising=False)

        workspace = MagicMock()
        workspace.proxy_url = "http://envoy:10000"
        env = await _build_agent_env(workspace, "sess-1", ["syntropic137/syntropic137"])
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
        env = await _build_agent_env(workspace, "sess-1", ["syntropic137/syntropic137"])
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
        env = await _build_agent_env(workspace, "sess-1", ["syntropic137/syntropic137"])
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
        env = await _build_agent_env(workspace, "sess-1", ["syntropic137/syntropic137"])
        assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-pref"
        assert "ANTHROPIC_API_KEY" not in env

    async def test_raises_without_proxy(self) -> None:
        from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
            _build_agent_env,
        )

        workspace = MagicMock()
        workspace.proxy_url = None  # sidecar not running
        with pytest.raises(RuntimeError, match="proxy not available"):
            await _build_agent_env(workspace, "sess-1", ["syntropic137/syntropic137"])


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


# =========================================================================
# WorkspaceProvisionHandler — claude plugin materialization (issue #726, PR2)
# =========================================================================


@pytest.mark.unit
class TestWorkspaceProvisionClaudePlugins:
    """Verify the PR2 materialization branch of WorkspaceProvisionHandler."""

    @pytest.mark.anyio
    async def test_materializes_plugins_and_appends_plugin_dir_flags(self) -> None:
        from syn_domain.contexts.orchestration._shared.resolved_claude_plugin import (
            ResolvedClaudePlugin,
        )
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

        materializer = AsyncMock()
        materializer.fetch_for_workspace = AsyncMock(
            return_value=[
                (".syn-plugins/hello/.claude-plugin/plugin.json", b'{"name":"hello"}'),
                (".syn-plugins/hello/skills/greet/SKILL.md", b"hi"),
            ],
        )

        handler = WorkspaceProvisionHandler(
            workspace_service=workspace_service,
            prompt_builder=fake_prompt_builder,
            command_builder=fake_command_builder,
            claude_plugin_materializer=materializer,
        )

        plugin = ResolvedClaudePlugin(
            name="hello",
            source_url="https://github.com/example/hello",
            version="0.0.1",
            resolved_sha="sha-hello",
            tree_storage_prefix="prefix/sha-hello",
        )
        phase = ExecutablePhase(
            phase_id="phase-1",
            name="Phase 1",
            order=1,
            description="",
            agent_config=AgentConfiguration(),
            prompt_template="Do the task",
            output_artifact_type="text",
            claude_plugins=(plugin,),
        )
        todo = TodoItem(
            execution_id="exec-1",
            action=TodoAction.PROVISION_WORKSPACE,
            phase_id="phase-1",
        )

        with patch("syn_adapters.workspace_backends.service.SetupPhaseSecrets") as MockSecrets:
            MockSecrets.create = AsyncMock(return_value=MagicMock())
            result = await handler.handle(
                todo=todo,
                phase=phase,
                workflow_id="wf-1",
                session_id="sess-1",
                repos=[],
            )

        # The materializer was consulted with the resolved plugin tuple.
        materializer.fetch_for_workspace.assert_awaited_once_with((plugin,))

        # Workspace received the materialized files via inject_files at least once
        # with the .syn-plugins/<name>/* shape.
        plugin_inject_calls = [
            call
            for call in workspace.inject_files.call_args_list
            if any(p.startswith(".syn-plugins/hello/") for p, _ in call.args[0])
        ]
        assert plugin_inject_calls, "expected at least one inject_files call with plugin paths"

        # The constructed claude command includes a --plugin-dir flag for the plugin.
        assert "--plugin-dir" in result.claude_cmd
        flag_index = result.claude_cmd.index("--plugin-dir")
        assert result.claude_cmd[flag_index + 1] == "/workspace/.syn-plugins/hello"

    @pytest.mark.anyio
    async def test_skips_materialization_when_phase_has_no_plugins(self) -> None:
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

        materializer = AsyncMock()
        materializer.fetch_for_workspace = AsyncMock(return_value=[])

        handler = WorkspaceProvisionHandler(
            workspace_service=workspace_service,
            prompt_builder=fake_prompt_builder,
            command_builder=fake_command_builder,
            claude_plugin_materializer=materializer,
        )
        phase = ExecutablePhase(
            phase_id="phase-1",
            name="Phase 1",
            order=1,
            description="",
            agent_config=AgentConfiguration(),
            prompt_template="Do the task",
            output_artifact_type="text",
        )
        todo = TodoItem(
            execution_id="exec-1",
            action=TodoAction.PROVISION_WORKSPACE,
            phase_id="phase-1",
        )

        with patch("syn_adapters.workspace_backends.service.SetupPhaseSecrets") as MockSecrets:
            MockSecrets.create = AsyncMock(return_value=MagicMock())
            result = await handler.handle(
                todo=todo,
                phase=phase,
                workflow_id="wf-1",
                session_id="sess-1",
                repos=[],
            )

        materializer.fetch_for_workspace.assert_not_called()
        assert "--plugin-dir" not in result.claude_cmd


# =========================================================================
# WorkspaceProvisionHandler - skill materialization + install (issue #772)
# =========================================================================


def _make_skill_provision_handler(
    *,
    workspace: AsyncMock,
    skill_materializer: AsyncMock | None,
) -> tuple[object, AsyncMock]:
    """Build a WorkspaceProvisionHandler wired for the skill-install branch."""
    from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
        WorkspaceProvisionHandler,
    )

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
        skill_materializer=skill_materializer,
    )
    return handler, workspace_cm


def _make_resolved_skill(name: str = "code-review", resolved_sha: str = "sha-1") -> object:
    from syn_domain.contexts.orchestration._shared.resolved_skill import ResolvedSkill

    return ResolvedSkill(
        skill_name=name,
        source_url="https://github.com/example/code-review",
        version="1.0.0",
        resolved_sha=resolved_sha,
        tree_storage_prefix=f"prefix/{resolved_sha}",
    )


def _make_skill_phase(
    *,
    provider: str = "codex",
    skills: tuple[object, ...],
) -> object:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        AgentConfiguration,
        ExecutablePhase,
    )

    return ExecutablePhase(
        phase_id="phase-1",
        name="Phase 1",
        order=1,
        description="",
        agent_config=AgentConfiguration(provider=provider),
        prompt_template="Do the task",
        output_artifact_type="text",
        skills=skills,
    )


def _make_skill_todo() -> object:
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem

    return TodoItem(
        execution_id="exec-1",
        action=TodoAction.PROVISION_WORKSPACE,
        phase_id="phase-1",
    )


@pytest.mark.unit
def test_skills_cli_agent_keys_table_matches_the_skills_cli_registry() -> None:
    """Pin the agent-key translation table itself, not just the selector.

    The values are the vercel skills-CLI agent ids, verified against the CLI
    bundled in the omni-agent workspace image (skills 1.5.14): the agent
    registry in ``dist/cli.mjs`` keys entries by exactly these ids, and
    ``skills add --agent <id>`` installs into that entry's ``skillsDir``:

        claude-code -> .claude/skills
        codex       -> .agents/skills
        gemini-cli  -> .agents/skills

    ``gemini`` (without the ``-cli`` suffix) is only a display alias the CLI
    maps ONTO ``gemini-cli``; the registry key is the suffixed form. Getting
    any of these wrong installs the skill where the harness never looks, and
    ``skills list`` still reports success (it does not filter by agent), so
    this table is the only place the mistake is catchable.
    """
    from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
        _SKILLS_CLI_AGENT_KEYS,
    )

    assert _SKILLS_CLI_AGENT_KEYS == {
        "claude": "claude-code",
        "codex": "codex",
        "gemini": "gemini-cli",
    }
    # The keys are our provider vocabulary; both headless providers must map.
    assert _SKILLS_CLI_AGENT_KEYS[AgentProvider.CLAUDE] == "claude-code"
    assert _SKILLS_CLI_AGENT_KEYS[AgentProvider.CODEX] == "codex"
    # claude-interactive is deliberately absent: the selector resolves it to a
    # pane agent_id first, so a raw lookup on it must miss.


@pytest.mark.unit
def test_skills_cli_agent_selector_keys_by_provider_for_headless() -> None:
    from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
        _SKILLS_CLI_AGENT_KEYS,
    )

    # The phase's provider IS the skills-CLI agent selector now that the
    # tmux pane selector (agent_id) is gone.
    assert _SKILLS_CLI_AGENT_KEYS[AgentProvider.CLAUDE] == "claude-code"
    assert _SKILLS_CLI_AGENT_KEYS[AgentProvider.CODEX] == "codex"


@pytest.mark.unit
class TestWorkspaceProvisionSkills:
    """Verify the #772 skill materialization + install branch of WorkspaceProvisionHandler."""

    @pytest.mark.anyio
    async def test_skills_installed_for_phase_agent(self) -> None:
        from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
            ExecutionResult,
        )

        workspace = AsyncMock()
        workspace.proxy_url = "http://envoy:10000"
        workspace.run_setup_phase = AsyncMock(return_value=MagicMock(exit_code=0))
        workspace.inject_files = AsyncMock()
        workspace.workspace_id = "ws-test"
        workspace.execute = AsyncMock(
            return_value=ExecutionResult(exit_code=0, success=True, duration_ms=1.0)
        )

        skill = _make_resolved_skill()
        materializer = AsyncMock()
        materializer.fetch_for_workspace = AsyncMock(
            return_value=[(".syn-skills/code-review/SKILL.md", b"content")],
        )

        handler, _ = _make_skill_provision_handler(
            workspace=workspace, skill_materializer=materializer
        )
        phase = _make_skill_phase(provider="codex", skills=(skill,))
        todo = _make_skill_todo()

        with patch("syn_adapters.workspace_backends.service.SetupPhaseSecrets") as MockSecrets:
            MockSecrets.create = AsyncMock(return_value=MagicMock())
            await handler.handle(
                todo=todo,
                phase=phase,
                workflow_id="wf-1",
                session_id="sess-1",
                repos=[],
            )

        materializer.fetch_for_workspace.assert_awaited_once_with((skill,))
        workspace.execute.assert_awaited_with(
            ["skills", "add", "/workspace/.syn-skills/code-review", "--agent", "codex", "-y"],
            timeout_seconds=120,
            working_directory="/workspace",
        )

    @pytest.mark.anyio
    async def test_skill_install_failure_raises(self) -> None:
        from syn_domain.contexts.orchestration._shared.skill_errors import SkillInstallFailed
        from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
            ExecutionResult,
        )

        workspace = AsyncMock()
        workspace.proxy_url = "http://envoy:10000"
        workspace.run_setup_phase = AsyncMock(return_value=MagicMock(exit_code=0))
        workspace.inject_files = AsyncMock()
        workspace.workspace_id = "ws-test"
        workspace.execute = AsyncMock(
            return_value=ExecutionResult(
                exit_code=1, success=False, duration_ms=1.0, stdout="", stderr="boom"
            )
        )

        skill = _make_resolved_skill()
        materializer = AsyncMock()
        materializer.fetch_for_workspace = AsyncMock(return_value=[])

        handler, _ = _make_skill_provision_handler(
            workspace=workspace, skill_materializer=materializer
        )
        phase = _make_skill_phase(provider="codex", skills=(skill,))
        todo = _make_skill_todo()

        with patch("syn_adapters.workspace_backends.service.SetupPhaseSecrets") as MockSecrets:
            MockSecrets.create = AsyncMock(return_value=MagicMock())
            with pytest.raises(SkillInstallFailed, match="code-review"):
                await handler.handle(
                    todo=todo,
                    phase=phase,
                    workflow_id="wf-1",
                    session_id="sess-1",
                    repos=[],
                )

    @pytest.mark.anyio
    async def test_skills_declared_but_no_materializer_raises(self) -> None:
        workspace = AsyncMock()
        workspace.proxy_url = "http://envoy:10000"
        workspace.run_setup_phase = AsyncMock(return_value=MagicMock(exit_code=0))
        workspace.inject_files = AsyncMock()
        workspace.workspace_id = "ws-test"

        skill = _make_resolved_skill()
        handler, _ = _make_skill_provision_handler(workspace=workspace, skill_materializer=None)
        phase = _make_skill_phase(provider="codex", skills=(skill,))
        todo = _make_skill_todo()

        with patch("syn_adapters.workspace_backends.service.SetupPhaseSecrets") as MockSecrets:
            MockSecrets.create = AsyncMock(return_value=MagicMock())
            with pytest.raises(RuntimeError, match="no skill materializer is wired"):
                await handler.handle(
                    todo=todo,
                    phase=phase,
                    workflow_id="wf-1",
                    session_id="sess-1",
                    repos=[],
                )

    @pytest.mark.anyio
    async def test_unknown_provider_raises(self) -> None:
        """An unrunnable provider is refused BEFORE any auth is staged.

        This used to surface as ``SkillInstallFailed`` ("no skills-cli agent
        key") deep in skill installation, which meant a phase whose provider
        the platform cannot run had already been handed credentials, and a
        skill-less phase was not stopped at all (PR #875 review). Provision now
        validates the provider up front, so the refusal is the same for every
        phase regardless of whether it declares skills.
        """
        from syn_shared.agents import UnsupportedAgentProviderError

        workspace = AsyncMock()
        workspace.proxy_url = "http://envoy:10000"
        workspace.run_setup_phase = AsyncMock(return_value=MagicMock(exit_code=0))
        workspace.inject_files = AsyncMock()
        workspace.workspace_id = "ws-test"
        workspace.execute = AsyncMock()

        skill = _make_resolved_skill()
        materializer = AsyncMock()
        materializer.fetch_for_workspace = AsyncMock(return_value=[])

        handler, _ = _make_skill_provision_handler(
            workspace=workspace, skill_materializer=materializer
        )
        phase = _make_skill_phase(provider="mystery", skills=(skill,))
        todo = _make_skill_todo()

        with patch("syn_adapters.workspace_backends.service.SetupPhaseSecrets") as MockSecrets:
            MockSecrets.create = AsyncMock(return_value=MagicMock())
            with pytest.raises(UnsupportedAgentProviderError, match="mystery"):
                await handler.handle(
                    todo=todo,
                    phase=phase,
                    workflow_id="wf-1",
                    session_id="sess-1",
                    repos=[],
                )
        workspace.execute.assert_not_awaited()

    @pytest.mark.anyio
    async def test_conflicting_skill_versions_raises(self) -> None:
        """Task 7 review note: same skill_name with differing resolved_sha must be rejected.

        Identity-triple dedup at the merge layer means a workflow-level and
        phase-level skill declaration could legitimately reference two
        different versions of the same skill_name. Both would materialize to
        the same ``.syn-skills/<skill_name>/`` path, silently clobbering one
        version with the other. Guard this explicitly rather than let the
        last-materialized version win unnoticed.
        """
        from syn_domain.contexts.orchestration._shared.skill_errors import SkillInstallFailed

        workspace = AsyncMock()
        workspace.proxy_url = "http://envoy:10000"
        workspace.run_setup_phase = AsyncMock(return_value=MagicMock(exit_code=0))
        workspace.inject_files = AsyncMock()
        workspace.workspace_id = "ws-test"
        workspace.execute = AsyncMock()

        skill_v1 = _make_resolved_skill(name="code-review", resolved_sha="sha-1")
        skill_v2 = _make_resolved_skill(name="code-review", resolved_sha="sha-2")
        materializer = AsyncMock()
        materializer.fetch_for_workspace = AsyncMock(return_value=[])

        handler, _ = _make_skill_provision_handler(
            workspace=workspace, skill_materializer=materializer
        )
        phase = _make_skill_phase(provider="codex", skills=(skill_v1, skill_v2))
        todo = _make_skill_todo()

        with patch("syn_adapters.workspace_backends.service.SetupPhaseSecrets") as MockSecrets:
            MockSecrets.create = AsyncMock(return_value=MagicMock())
            with pytest.raises(SkillInstallFailed, match="conflicting versions of skill"):
                await handler.handle(
                    todo=todo,
                    phase=phase,
                    workflow_id="wf-1",
                    session_id="sess-1",
                    repos=[],
                )
        materializer.fetch_for_workspace.assert_not_called()
        workspace.execute.assert_not_awaited()


@pytest.mark.unit
class TestWorkspaceProvisionHandlerInjectsTheWholeTree:
    """The provisioning seam between the cache and the collector (#988).

    Everything upstream can carry the output tree correctly and everything
    downstream can inject it correctly, and the handoff still loses it here if
    this method forwards only the primary strings. Nothing else in the suite
    covers that one hop.
    """

    @pytest.mark.anyio
    async def test_the_file_tree_reaches_the_collector(self) -> None:
        from syn_domain.contexts.artifacts import PhaseOutputFile
        from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
            WorkspaceProvisionHandler,
        )
        from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
            PhaseOutputCache,
        )

        files = [PhaseOutputFile(source_path="artifacts/output/review.yaml", content="r")]
        cache = PhaseOutputCache(primary={"p-1": "r"}, files={"p-1": files})
        collector = AsyncMock()
        todo = TodoItem(
            execution_id="exec-1",
            action=TodoAction.PROVISION_WORKSPACE,
            phase_id="p-2",
        )

        await WorkspaceProvisionHandler._inject_phase_artifacts(
            MagicMock(),  # handler self is unused by this method's body
            MagicMock(),
            collector,
            ["p-1"],
            cache,
            todo,
        )

        kwargs = collector.inject_from_previous_phases_explicit.await_args.kwargs
        assert kwargs["phase_files"] == {"p-1": files}
        assert collector.inject_from_previous_phases_explicit.await_args.args[2] == {"p-1": "r"}
