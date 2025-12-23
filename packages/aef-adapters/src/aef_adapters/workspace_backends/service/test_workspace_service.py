"""Tests for WorkspaceService.

Run: pytest packages/aef-adapters/src/aef_adapters/workspace_backends/service/test_workspace_service.py -v
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aef_adapters.workspace_backends.service import WorkspaceBackend
from aef_domain.contexts.workspaces._shared.value_objects import (
    IsolationBackendType,
    TokenType,
    WorkspaceStatus,
)

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture(autouse=True)
def set_test_environment():
    """Ensure test environment for memory adapters."""
    with patch.dict(os.environ, {"APP_ENVIRONMENT": "test"}):
        yield


# =============================================================================
# WORKSPACE SERVICE TESTS
# =============================================================================


@pytest.mark.integration
class TestWorkspaceServiceMemory:
    """Test WorkspaceService with memory adapters."""

    @pytest.mark.asyncio
    async def test_create_memory_service(self) -> None:
        """Test creating memory service for testing."""
        from aef_adapters.workspace_backends.service import WorkspaceService

        service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY)
        assert service is not None

    @pytest.mark.asyncio
    async def test_create_workspace_context_manager(self) -> None:
        """Test workspace creation as context manager."""
        from aef_adapters.workspace_backends.service import WorkspaceService

        service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY)

        async with service.create_workspace(
            execution_id="exec-test-123",
            workflow_id="wf-test",
        ) as workspace:
            assert workspace.workspace_id is not None
            assert workspace.execution_id == "exec-test-123"
            assert workspace.isolation_handle is not None
            assert workspace.sidecar_handle is not None

    @pytest.mark.asyncio
    async def test_workspace_execute(self) -> None:
        """Test executing commands in workspace."""
        from aef_adapters.workspace_backends.service import WorkspaceService

        service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY)

        async with service.create_workspace(
            execution_id="exec-exec-test",
        ) as workspace:
            result = await workspace.execute(["echo", "hello"])

            assert result.success is True
            assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_workspace_inject_tokens(self) -> None:
        """Test token injection."""
        from aef_adapters.workspace_backends.service import (
            WorkspaceService,
        )

        service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY)

        async with service.create_workspace(
            execution_id="exec-token-test",
        ) as workspace:
            result = await workspace.inject_tokens([TokenType.ANTHROPIC])

            assert result.success is True
            assert TokenType.ANTHROPIC in result.tokens_injected
            assert workspace._tokens_injected is True

    @pytest.mark.asyncio
    async def test_workspace_auto_inject_tokens(self) -> None:
        """Test automatic token injection on creation."""
        from aef_adapters.workspace_backends.service import WorkspaceService

        service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY)

        async with service.create_workspace(
            execution_id="exec-auto-token",
            inject_tokens=True,
            token_types=[TokenType.ANTHROPIC, TokenType.GITHUB],
        ) as workspace:
            assert workspace._tokens_injected is True

    @pytest.mark.asyncio
    async def test_workspace_cleanup_on_exit(self) -> None:
        """Test that workspace is cleaned up on context exit."""
        from aef_adapters.workspace_backends.service import WorkspaceService

        service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY)

        async with service.create_workspace(
            execution_id="exec-cleanup",
        ) as workspace:
            # Workspace should be active
            assert workspace.status == WorkspaceStatus.READY

        # After exit, aggregate should show destroyed
        assert workspace.aggregate.status == WorkspaceStatus.DESTROYED

    @pytest.mark.asyncio
    async def test_workspace_without_sidecar(self) -> None:
        """Test creating workspace without sidecar."""
        from aef_adapters.workspace_backends.service import WorkspaceService

        service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY)

        async with service.create_workspace(
            execution_id="exec-no-sidecar",
            with_sidecar=False,
        ) as workspace:
            assert workspace.sidecar_handle is None
            assert workspace.proxy_url is None

    @pytest.mark.asyncio
    async def test_workspace_proxy_url(self) -> None:
        """Test proxy URL is available when sidecar is started."""
        from aef_adapters.workspace_backends.service import WorkspaceService

        service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY)

        async with service.create_workspace(
            execution_id="exec-proxy",
            with_sidecar=True,
        ) as workspace:
            assert workspace.proxy_url is not None
            assert "8080" in workspace.proxy_url

    @pytest.mark.asyncio
    async def test_workspace_status_lifecycle(self) -> None:
        """Test workspace status through lifecycle."""
        from aef_adapters.workspace_backends.service import WorkspaceService

        service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY)

        async with service.create_workspace(
            execution_id="exec-lifecycle",
        ) as workspace:
            # After creation, should be READY
            assert workspace.status == WorkspaceStatus.READY

        # After exit, should be DESTROYED
        assert workspace.aggregate.status == WorkspaceStatus.DESTROYED


class TestWorkspaceServiceDocker:
    """Test WorkspaceService with Docker adapters (mocked)."""

    @pytest.mark.asyncio
    async def test_create_docker_service(self) -> None:
        """Test creating Docker service."""
        from aef_adapters.workspace_backends.service import WorkspaceService

        # Mock the token vending service
        with patch("aef_tokens.vending.get_token_vending_service") as mock_tvs:
            mock_tvs.return_value = MagicMock()
            service = WorkspaceService.create()
            assert service is not None

    @pytest.mark.asyncio
    async def test_docker_workspace_lifecycle(self) -> None:
        """Test Docker workspace lifecycle with mocked Docker."""
        from aef_adapters.workspace_backends.service import WorkspaceService

        # Create mocked adapters
        mock_isolation = MagicMock()
        mock_isolation.create = AsyncMock(
            return_value=MagicMock(
                isolation_id="container-123",
                isolation_type="docker",
                workspace_path="/workspace",
            )
        )
        mock_isolation.execute = AsyncMock(
            return_value=MagicMock(
                exit_code=0,
                success=True,
                stdout="Hello!",
                stderr="",
            )
        )
        mock_isolation.destroy = AsyncMock()

        mock_sidecar = MagicMock()
        mock_sidecar.start = AsyncMock(
            return_value=MagicMock(
                sidecar_id="sidecar-456",
                proxy_url="http://sidecar:8080",
            )
        )
        mock_sidecar.stop = AsyncMock()
        mock_sidecar.configure_tokens = AsyncMock()

        mock_token_injection = MagicMock()
        mock_token_injection.inject = AsyncMock(
            return_value=MagicMock(
                success=True,
                tokens_injected=(TokenType.ANTHROPIC,),
            )
        )
        mock_token_injection.revoke = AsyncMock()

        mock_event_stream = MagicMock()

        service = WorkspaceService(
            isolation=mock_isolation,
            sidecar=mock_sidecar,
            token_injection=mock_token_injection,
            event_stream=mock_event_stream,
        )

        async with service.create_workspace(
            execution_id="exec-docker",
            inject_tokens=True,
        ) as workspace:
            # Should have created isolation
            mock_isolation.create.assert_called_once()

            # Should have started sidecar
            mock_sidecar.start.assert_called_once()

            # Should have injected tokens
            mock_token_injection.inject.assert_called_once()

            # Execute a command
            result = await workspace.execute(["echo", "test"])
            assert result.success is True
            mock_isolation.execute.assert_called()

        # Should have cleaned up
        mock_token_injection.revoke.assert_called_once()
        mock_sidecar.stop.assert_called_once()
        mock_isolation.destroy.assert_called_once()


class TestWorkspaceServiceConfig:
    """Test WorkspaceServiceConfig."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        from aef_adapters.workspace_backends.service import WorkspaceServiceConfig

        config = WorkspaceServiceConfig()

        assert config.backend == IsolationBackendType.DOCKER_HARDENED
        assert config.memory_limit_mb == 512
        assert config.cpu_limit_cores == 1.0
        assert config.timeout_seconds == 3600
        assert "api.anthropic.com" in config.allowed_hosts
        assert config.default_token_ttl == 300

    def test_custom_config(self) -> None:
        """Test custom configuration."""
        from aef_adapters.workspace_backends.service import WorkspaceServiceConfig

        config = WorkspaceServiceConfig(
            backend=IsolationBackendType.GVISOR,
            memory_limit_mb=1024,
            cpu_limit_cores=2.0,
            image="custom-image:v1",
        )

        assert config.backend == IsolationBackendType.GVISOR
        assert config.memory_limit_mb == 1024
        assert config.cpu_limit_cores == 2.0
        assert config.image == "custom-image:v1"


class TestManagedWorkspace:
    """Test ManagedWorkspace functionality."""

    @pytest.mark.asyncio
    async def test_managed_workspace_properties(self) -> None:
        """Test ManagedWorkspace properties."""
        from aef_adapters.workspace_backends.service import WorkspaceService

        service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY)

        async with service.create_workspace(
            execution_id="exec-props",
            workflow_id="wf-props",
        ) as workspace:
            assert workspace.workspace_id is not None
            assert workspace.execution_id == "exec-props"
            assert workspace.proxy_url is not None
            assert workspace.status == WorkspaceStatus.READY

    @pytest.mark.asyncio
    async def test_inject_tokens_without_sidecar_raises(self) -> None:
        """Test that injecting tokens without sidecar raises error."""
        from aef_adapters.workspace_backends.service import WorkspaceService

        service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY)

        async with service.create_workspace(
            execution_id="exec-no-sidecar",
            with_sidecar=False,
        ) as workspace:
            with pytest.raises(RuntimeError, match="No sidecar"):
                await workspace.inject_tokens([TokenType.ANTHROPIC])


class TestWorkspaceServiceIntegration:
    """Integration tests composing all components."""

    @pytest.mark.asyncio
    async def test_full_workflow_simulation(self) -> None:
        """Simulate a full workflow execution."""
        from aef_adapters.workspace_backends.service import WorkspaceService

        service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY)

        # Simulate multi-phase workflow
        for phase in ["research", "implement", "review"]:
            async with service.create_workspace(
                execution_id=f"exec-{phase}",
                workflow_id="wf-multi",
                phase_id=phase,
                inject_tokens=True,
            ) as workspace:
                # Execute phase
                result = await workspace.execute(["echo", f"Phase: {phase}"])
                assert result.success is True

        # All workspaces should be cleaned up automatically
