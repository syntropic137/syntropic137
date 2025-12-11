"""Tests for orchestration factory functions.

Tests workspace factory integration with WorkspaceRouter.
See ADR-021: Isolated Workspace Architecture.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from aef_adapters.agents.agentic_types import Workspace, WorkspaceConfig


@pytest.fixture
def workspace_config() -> WorkspaceConfig:
    """Create a test workspace config."""
    return WorkspaceConfig(
        session_id="test-session-123",
        base_dir=Path("/tmp/test-workspaces"),
        workflow_id="workflow-abc",
        phase_id="phase-1",
    )


class TestGetWorkspace:
    """Tests for get_workspace function."""

    @pytest.mark.asyncio
    async def test_creates_isolated_workspace(
        self,
        workspace_config: WorkspaceConfig,
    ) -> None:
        """Should use WorkspaceRouter to create isolated workspace."""
        from contextlib import asynccontextmanager

        from aef_adapters.orchestration.factory import get_workspace

        mock_isolated = AsyncMock()
        mock_isolated.workspace_path = "/isolated/path"

        # Create a proper async context manager for the router
        @asynccontextmanager
        async def mock_create(_config):
            yield mock_isolated

        with patch("aef_adapters.workspaces.get_workspace_router") as mock_router:
            mock_router_instance = AsyncMock()
            mock_router.return_value = mock_router_instance
            mock_router_instance.create = mock_create

            async with get_workspace(workspace_config) as workspace:
                assert isinstance(workspace, Workspace)
                assert workspace.config == workspace_config

    @pytest.mark.asyncio
    async def test_workspace_has_router_reference(
        self,
        workspace_config: WorkspaceConfig,
    ) -> None:
        """Should attach router reference for command execution."""
        from contextlib import asynccontextmanager

        from aef_adapters.orchestration.factory import get_workspace

        mock_isolated = AsyncMock()
        mock_isolated.workspace_path = "/isolated/path"

        @asynccontextmanager
        async def mock_create(_config):
            yield mock_isolated

        with patch("aef_adapters.workspaces.get_workspace_router") as mock_router:
            mock_router_instance = AsyncMock()
            mock_router.return_value = mock_router_instance
            mock_router_instance.create = mock_create

            async with get_workspace(workspace_config) as workspace:
                # Should have router reference for command execution
                assert hasattr(workspace, "_router")
                assert hasattr(workspace, "_isolated_workspace")


class TestExecuteInWorkspace:
    """Tests for execute_in_workspace function."""

    @pytest.mark.asyncio
    async def test_executes_via_router(
        self,
        workspace_config: WorkspaceConfig,
    ) -> None:
        """Should execute commands through WorkspaceRouter."""
        from aef_adapters.orchestration.factory import execute_in_workspace

        mock_router = AsyncMock()
        mock_router.execute_command.return_value = (0, "output", "")

        mock_isolated = AsyncMock()

        workspace = Workspace(path=Path("/test"), config=workspace_config)
        workspace._router = mock_router  # type: ignore[attr-defined]
        workspace._isolated_workspace = mock_isolated  # type: ignore[attr-defined]

        exit_code, stdout, _stderr = await execute_in_workspace(
            workspace,
            ["echo", "hello"],
        )

        assert exit_code == 0
        assert stdout == "output"
        mock_router.execute_command.assert_called_once_with(
            mock_isolated,
            ["echo", "hello"],
            None,  # timeout
            None,  # cwd
        )

    @pytest.mark.asyncio
    async def test_raises_for_non_isolated_workspace(
        self,
        workspace_config: WorkspaceConfig,
    ) -> None:
        """Should raise error if workspace wasn't created via get_workspace."""
        from aef_adapters.orchestration.factory import execute_in_workspace

        # Create workspace without router reference
        workspace = Workspace(path=Path("/test"), config=workspace_config)

        with pytest.raises(RuntimeError) as exc_info:
            await execute_in_workspace(workspace, ["echo", "hello"])

        assert "not created via get_workspace" in str(exc_info.value)


class TestGetWorkspaceLocal:
    """Tests for get_workspace_local function (dev/test only)."""

    @pytest.mark.asyncio
    async def test_creates_local_workspace(
        self,
        workspace_config: WorkspaceConfig,
        tmp_path: Path,
    ) -> None:
        """Should create LocalWorkspace for testing."""
        from aef_adapters.orchestration.factory import get_workspace_local

        # Override base_dir to use tmp_path
        config = WorkspaceConfig(
            session_id=workspace_config.session_id,
            base_dir=tmp_path,
            workflow_id=workspace_config.workflow_id,
            phase_id=workspace_config.phase_id,
        )

        async with get_workspace_local(config) as workspace:
            assert isinstance(workspace, Workspace)
            # LocalWorkspace creates in base_dir/session_id
            assert workspace.path.parent == tmp_path


class TestAgenticAgentFactory:
    """Tests for get_agentic_agent function."""

    def test_returns_claude_agent(self) -> None:
        """Should return Claude agentic agent when requested."""
        from aef_adapters.orchestration.factory import get_agentic_agent

        # Mock the ClaudeAgenticAgent (imported inside get_agentic_agent)
        with patch("aef_adapters.agents.claude_agentic.ClaudeAgenticAgent") as mock_cls:
            mock_agent = AsyncMock()
            mock_agent.is_available = True
            mock_cls.return_value = mock_agent

            agent = get_agentic_agent("claude")

            assert agent.is_available
            mock_cls.assert_called_once()

    def test_raises_for_unsupported_provider(self) -> None:
        """Should raise error for unsupported provider."""
        from aef_adapters.orchestration.factory import get_agentic_agent

        with pytest.raises(ValueError) as exc_info:
            get_agentic_agent("unsupported")

        assert "Unsupported agentic provider" in str(exc_info.value)

    def test_normalizes_provider_name(self) -> None:
        """Should normalize provider names (case insensitive)."""
        from aef_adapters.orchestration.factory import get_agentic_agent

        with patch("aef_adapters.agents.claude_agentic.ClaudeAgenticAgent") as mock_cls:
            mock_agent = AsyncMock()
            mock_agent.is_available = True
            mock_cls.return_value = mock_agent

            # Should work with different cases
            get_agentic_agent("Claude")
            get_agentic_agent("CLAUDE")
            get_agentic_agent("anthropic")

            assert mock_cls.call_count == 3
