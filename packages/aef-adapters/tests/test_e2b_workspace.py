"""Tests for E2BWorkspace.

These tests verify the E2B cloud sandbox workspace implementation.
All tests mock the E2B API calls since they require network access.

See ADR-021: Isolated Workspace Architecture
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aef_adapters.agents.agentic_types import WorkspaceConfig
from aef_adapters.workspaces import E2BWorkspace
from aef_adapters.workspaces.base import BaseIsolatedWorkspace
from aef_adapters.workspaces.types import IsolatedWorkspace
from aef_shared.settings import IsolationBackend

if TYPE_CHECKING:
    from pathlib import Path

# Check if aiohttp is available for integration tests
try:
    import aiohttp  # noqa: F401

    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

aiohttp_required = pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")


class TestE2BWorkspaceClass:
    """Tests for E2BWorkspace class attributes."""

    def test_isolation_backend(self) -> None:
        """E2BWorkspace should have CLOUD backend."""
        assert E2BWorkspace.isolation_backend == IsolationBackend.CLOUD

    def test_inherits_from_base(self) -> None:
        """E2BWorkspace should inherit from BaseIsolatedWorkspace."""
        assert issubclass(E2BWorkspace, BaseIsolatedWorkspace)

    def test_has_api_config(self) -> None:
        """Should have E2B API configuration."""
        assert hasattr(E2BWorkspace, "API_BASE_URL")
        assert hasattr(E2BWorkspace, "DEFAULT_TEMPLATE")
        assert "e2b.dev" in E2BWorkspace.API_BASE_URL


class TestIsAvailable:
    """Tests for is_available() method."""

    def test_returns_false_when_no_api_key(self) -> None:
        """Should return False when no API key is configured."""
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("aef_shared.settings.get_settings") as mock_settings,
        ):
            mock_settings.return_value.workspace.cloud_api_key = None
            assert E2BWorkspace.is_available() is False

    def test_returns_true_when_api_key_set(self) -> None:
        """Should return True when API key is configured."""
        with patch("aef_shared.settings.get_settings") as mock_settings:
            mock_api_key = MagicMock()
            mock_api_key.get_secret_value.return_value = "test-api-key"
            mock_settings.return_value.workspace.cloud_api_key = mock_api_key
            assert E2BWorkspace.is_available() is True

    def test_checks_env_var_as_fallback(self) -> None:
        """Should check environment variable as fallback."""
        with patch("aef_shared.settings.get_settings") as mock_settings:
            mock_settings.side_effect = Exception("Settings error")
            with patch.dict(os.environ, {"AEF_WORKSPACE_CLOUD_API_KEY": "env-key"}, clear=True):
                assert E2BWorkspace.is_available() is True


@aiohttp_required
class TestCreateSandbox:
    """Tests for _create_sandbox() method."""

    @pytest.mark.asyncio
    async def test_creates_sandbox_via_api(self) -> None:
        """Should create sandbox via E2B API."""
        mock_response = AsyncMock()
        mock_response.status = 201
        mock_response.json = AsyncMock(return_value={"sandboxId": "sandbox-123"})

        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response))
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            sandbox_id = await E2BWorkspace._create_sandbox(
                api_key="test-key",
                template="base",
                timeout=3600,
            )
            assert sandbox_id == "sandbox-123"

    @pytest.mark.asyncio
    async def test_raises_on_api_error(self) -> None:
        """Should raise RuntimeError on API error."""
        mock_response = AsyncMock()
        mock_response.status = 401
        mock_response.text = AsyncMock(return_value="Unauthorized")

        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response))
        )

        with (
            patch("aiohttp.ClientSession", return_value=mock_session),
            pytest.raises(RuntimeError, match="E2B sandbox creation failed"),
        ):
            await E2BWorkspace._create_sandbox(
                api_key="invalid-key",
                template="base",
                timeout=3600,
            )


@aiohttp_required
class TestKillSandbox:
    """Tests for _kill_sandbox() method."""

    @pytest.mark.asyncio
    async def test_kills_sandbox_via_api(self) -> None:
        """Should kill sandbox via E2B API."""
        mock_response = AsyncMock()
        mock_response.status = 204

        mock_session = AsyncMock()
        mock_session.delete = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response))
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            # Should not raise
            await E2BWorkspace._kill_sandbox(
                api_key="test-key",
                sandbox_id="sandbox-123",
            )

    @pytest.mark.asyncio
    async def test_handles_404_gracefully(self) -> None:
        """Should handle 404 (already gone) gracefully."""
        mock_response = AsyncMock()
        mock_response.status = 404

        mock_session = AsyncMock()
        mock_session.delete = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response))
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            # Should not raise
            await E2BWorkspace._kill_sandbox(
                api_key="test-key",
                sandbox_id="sandbox-123",
            )


@aiohttp_required
class TestExecuteCommand:
    """Tests for execute_command() method."""

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> IsolatedWorkspace:
        """Create a mock workspace."""
        config = WorkspaceConfig(session_id="test", base_dir=tmp_path)
        ws = IsolatedWorkspace(
            path=tmp_path,
            config=config,
            isolation_backend=IsolationBackend.CLOUD,
            sandbox_id="sandbox-123",
        )
        ws.mark_started()
        return ws

    @pytest.mark.asyncio
    async def test_raises_when_no_sandbox(self, tmp_path: Path) -> None:
        """Should raise when sandbox_id is not set."""
        config = WorkspaceConfig(session_id="test", base_dir=tmp_path)
        workspace = IsolatedWorkspace(
            path=tmp_path,
            config=config,
            isolation_backend=IsolationBackend.CLOUD,
            sandbox_id=None,
        )

        with pytest.raises(RuntimeError, match="not running"):
            await E2BWorkspace.execute_command(workspace, ["ls"])

    @pytest.mark.asyncio
    async def test_runs_process_via_api(self, workspace: IsolatedWorkspace) -> None:
        """Should run process via E2B API."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "exitCode": 0,
                "stdout": "hello\n",
                "stderr": "",
            }
        )

        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response))
        )

        with (
            patch("aiohttp.ClientSession", return_value=mock_session),
            patch("aef_shared.settings.get_settings") as mock_settings,
        ):
            mock_api_key = MagicMock()
            mock_api_key.get_secret_value.return_value = "test-key"
            mock_settings.return_value.workspace.cloud_api_key = mock_api_key

            exit_code, stdout, stderr = await E2BWorkspace.execute_command(
                workspace, ["echo", "hello"]
            )

            assert exit_code == 0
            assert stdout == "hello\n"
            assert stderr == ""


@aiohttp_required
class TestHealthCheck:
    """Tests for health_check() method."""

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> IsolatedWorkspace:
        """Create a mock workspace."""
        config = WorkspaceConfig(session_id="test", base_dir=tmp_path)
        ws = IsolatedWorkspace(
            path=tmp_path,
            config=config,
            isolation_backend=IsolationBackend.CLOUD,
            sandbox_id="sandbox-123",
        )
        ws.mark_started()
        return ws

    @pytest.mark.asyncio
    async def test_returns_false_when_not_running(self, tmp_path: Path) -> None:
        """Should return False when workspace is not running."""
        config = WorkspaceConfig(session_id="test", base_dir=tmp_path)
        workspace = IsolatedWorkspace(
            path=tmp_path,
            config=config,
            isolation_backend=IsolationBackend.CLOUD,
            sandbox_id="sandbox-123",
        )
        # Not marked as started

        result = await E2BWorkspace.health_check(workspace)
        assert result is False

    @pytest.mark.asyncio
    async def test_runs_true_command(self, workspace: IsolatedWorkspace) -> None:
        """Should run 'true' command to check health."""
        with patch.object(
            E2BWorkspace,
            "execute_command",
            return_value=(0, "", ""),
        ) as mock_exec:
            result = await E2BWorkspace.health_check(workspace)

            assert result is True
            mock_exec.assert_called_once()
            # Check 'true' was the command
            call_args = mock_exec.call_args
            assert call_args[0][1] == ["true"]


class TestInheritedFunctionality:
    """Tests to verify inherited functionality from BaseIsolatedWorkspace."""

    def test_inherits_inject_context(self) -> None:
        """Should inherit inject_context from BaseIsolatedWorkspace."""
        assert hasattr(E2BWorkspace, "inject_context")
        assert E2BWorkspace.inject_context.__func__ is BaseIsolatedWorkspace.inject_context.__func__

    def test_inherits_collect_artifacts(self) -> None:
        """Should inherit collect_artifacts from BaseIsolatedWorkspace."""
        assert hasattr(E2BWorkspace, "collect_artifacts")
        assert (
            E2BWorkspace.collect_artifacts.__func__
            is BaseIsolatedWorkspace.collect_artifacts.__func__
        )

    def test_inherits_setup_hooks(self) -> None:
        """Should inherit _setup_hooks from BaseIsolatedWorkspace."""
        assert hasattr(E2BWorkspace, "_setup_hooks")

    def test_inherits_setup_directories(self) -> None:
        """Should inherit _setup_directories from BaseIsolatedWorkspace."""
        assert hasattr(E2BWorkspace, "_setup_directories")
