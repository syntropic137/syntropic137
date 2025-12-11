"""Integration tests for isolated workspace architecture.

These tests verify end-to-end workspace lifecycle including:
- Workspace creation with different backends
- Context injection and artifact collection
- Command execution
- Proper cleanup

Some tests require Docker and are skipped if not available.

See ADR-021: Isolated Workspace Architecture
"""

from __future__ import annotations

import os
import shutil
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from aef_adapters.agents.agentic_types import WorkspaceConfig
from aef_adapters.workspaces import (
    GVisorWorkspace,
    HardenedDockerWorkspace,
    IsolatedWorkspaceConfig,
    WorkspaceRouter,
    get_workspace_router,
    reset_workspace_router,
)
from aef_shared.settings import IsolationBackend, WorkspaceSecuritySettings

if TYPE_CHECKING:
    from pathlib import Path


# Skip markers for optional integrations
docker_available = shutil.which("docker") is not None
skip_no_docker = pytest.mark.skipif(not docker_available, reason="Docker not installed")

# Check for environment variable to run slow Docker tests
run_docker_tests = os.environ.get("AEF_RUN_DOCKER_TESTS", "").lower() in ("1", "true")
skip_docker_slow = pytest.mark.skipif(
    not run_docker_tests, reason="Set AEF_RUN_DOCKER_TESTS=1 to run Docker integration tests"
)


class TestWorkspaceConfigIntegration:
    """Tests for workspace configuration integration."""

    def test_config_with_security_settings(self, tmp_path: Path) -> None:
        """Should create config with custom security settings."""
        base_config = WorkspaceConfig(
            session_id="test-session",
            base_dir=tmp_path,
            workflow_id="wf-123",
            phase_id="phase-1",
        )

        security = WorkspaceSecuritySettings(_env_file=None)

        config = IsolatedWorkspaceConfig(
            base_config=base_config,
            security=security,
            isolation_backend=IsolationBackend.GVISOR,
        )

        # Verify delegation works
        assert config.session_id == "test-session"
        assert config.workflow_id == "wf-123"
        assert config.phase_id == "phase-1"

        # Verify security settings
        assert config.security is not None
        assert config.security.allow_network is False
        assert config.security.max_memory == "512Mi"

        # Verify backend override
        assert config.isolation_backend == IsolationBackend.GVISOR

    def test_config_without_security_uses_defaults(self, tmp_path: Path) -> None:
        """Should use default security when not specified."""
        base_config = WorkspaceConfig(session_id="test", base_dir=tmp_path)
        config = IsolatedWorkspaceConfig(base_config=base_config)

        assert config.security is None  # Will use defaults at runtime
        assert config.isolation_backend is None  # Will auto-detect


class TestWorkspaceRouterIntegration:
    """Integration tests for WorkspaceRouter."""

    @pytest.fixture(autouse=True)
    def reset_router(self) -> None:
        """Reset singleton router before and after each test."""
        reset_workspace_router()
        yield
        reset_workspace_router()

    def test_router_singleton(self) -> None:
        """Singleton should return same instance."""
        router1 = get_workspace_router()
        router2 = get_workspace_router()
        assert router1 is router2

    def test_available_backends_returns_list(self) -> None:
        """Should return list of available backends."""
        router = WorkspaceRouter()
        available = router.get_available_backends()

        assert isinstance(available, list)
        for backend in available:
            assert isinstance(backend, IsolationBackend)

    @skip_no_docker
    def test_docker_backends_available_with_docker(self) -> None:
        """With Docker installed, Docker backends should be available."""
        router = WorkspaceRouter()
        available = router.get_available_backends()

        # At least one Docker backend should be available
        docker_backends = {IsolationBackend.GVISOR, IsolationBackend.DOCKER_HARDENED}
        assert len(docker_backends & set(available)) > 0

    def test_router_stats_initial(self) -> None:
        """Router stats should be initialized correctly."""
        router = WorkspaceRouter()

        assert router.stats.total_created == 0
        assert router.stats.active_count == 0
        assert router.stats.overflow_count == 0
        assert router.stats.failed_count == 0
        assert router.active_count == 0

    def test_backend_class_mapping(self) -> None:
        """Backend classes should be correctly mapped."""
        router = WorkspaceRouter()

        # Check all implemented backends
        assert router.get_backend_class(IsolationBackend.GVISOR) is GVisorWorkspace
        assert router.get_backend_class(IsolationBackend.DOCKER_HARDENED) is HardenedDockerWorkspace


class TestSecuritySettingsIntegration:
    """Integration tests for security settings."""

    def test_restrictive_defaults(self) -> None:
        """Default security should be maximally restrictive."""
        security = WorkspaceSecuritySettings(_env_file=None)

        # Network isolated
        assert security.allow_network is False
        assert security.get_allowed_hosts_list() == []

        # Filesystem protected
        assert security.read_only_root is True

        # Resource limits
        assert security.max_memory == "512Mi"
        assert security.max_cpu == 0.5
        assert security.max_pids == 100
        assert security.max_execution_time == 3600

    def test_environment_override(self) -> None:
        """Environment variables should override defaults."""
        env = {
            "AEF_SECURITY_ALLOW_NETWORK": "true",
            "AEF_SECURITY_MAX_MEMORY": "2Gi",
            "AEF_SECURITY_ALLOWED_HOSTS": "pypi.org,github.com",
        }

        with patch.dict(os.environ, env, clear=True):
            security = WorkspaceSecuritySettings(_env_file=None)

            assert security.allow_network is True
            assert security.max_memory == "2Gi"
            assert security.get_allowed_hosts_list() == ["pypi.org", "github.com"]


class TestWorkspaceLifecycle:
    """Tests for workspace lifecycle without requiring Docker."""

    def test_isolated_workspace_properties(self, tmp_path: Path) -> None:
        """IsolatedWorkspace should have correct properties."""
        from aef_adapters.workspaces.types import IsolatedWorkspace

        config = WorkspaceConfig(session_id="test", base_dir=tmp_path)
        workspace = IsolatedWorkspace(
            path=tmp_path / "workspace",
            config=config,
            isolation_backend=IsolationBackend.GVISOR,
            container_id="test-container",
        )

        # Check path properties
        assert workspace.context_dir == tmp_path / "workspace" / ".context"
        assert workspace.output_dir == tmp_path / "workspace" / "output"
        assert workspace.hooks_dir == tmp_path / "workspace" / ".claude" / "hooks"

        # Check lifecycle
        assert not workspace.is_running
        workspace.mark_started()
        assert workspace.is_running
        workspace.mark_terminated()
        assert not workspace.is_running

    def test_resource_usage_tracking(self, tmp_path: Path) -> None:
        """IsolatedWorkspace should track resource usage."""
        from aef_adapters.workspaces.types import IsolatedWorkspace

        config = WorkspaceConfig(session_id="test", base_dir=tmp_path)
        workspace = IsolatedWorkspace(
            path=tmp_path,
            config=config,
            isolation_backend=IsolationBackend.GVISOR,
        )

        # Initial values
        assert workspace.memory_used_bytes == 0
        assert workspace.cpu_time_seconds == 0.0

        # Update values
        workspace.update_resource_usage(
            memory_bytes=256 * 1024 * 1024,
            cpu_seconds=5.5,
            network_in=1024,
            network_out=512,
        )

        assert workspace.memory_used_bytes == 256 * 1024 * 1024
        assert workspace.cpu_time_seconds == 5.5
        assert workspace.network_bytes_in == 1024
        assert workspace.network_bytes_out == 512


class TestBackendAvailability:
    """Tests for backend availability detection."""

    @patch("sys.platform", "linux")
    @patch("shutil.which")
    def test_firecracker_requires_linux_and_kvm(self, mock_which) -> None:
        """Firecracker should require Linux with KVM."""
        from aef_adapters.workspaces import FirecrackerWorkspace

        mock_which.return_value = "/usr/bin/firecracker"

        # With KVM available
        with patch("pathlib.Path.exists", return_value=True):
            assert FirecrackerWorkspace.is_available() is True

    @patch("sys.platform", "darwin")
    def test_firecracker_unavailable_on_macos(self) -> None:
        """Firecracker should not be available on macOS."""
        from aef_adapters.workspaces import FirecrackerWorkspace

        assert FirecrackerWorkspace.is_available() is False

    @patch("shutil.which")
    def test_docker_backend_requires_docker(self, mock_which) -> None:
        """Docker backends should require Docker."""
        mock_which.return_value = None

        assert GVisorWorkspace.is_available() is False
        assert HardenedDockerWorkspace.is_available() is False

    @patch("shutil.which", return_value="/usr/bin/docker")
    def test_hardened_docker_only_needs_docker(self, _mock_which) -> None:
        """HardenedDockerWorkspace should work with just Docker."""
        assert HardenedDockerWorkspace.is_available() is True


@skip_docker_slow
class TestDockerIntegration:
    """Integration tests that require Docker.

    These tests actually create Docker containers and verify isolation.
    Set AEF_RUN_DOCKER_TESTS=1 to enable.
    """

    @pytest.fixture
    def config(self, tmp_path: Path) -> IsolatedWorkspaceConfig:
        """Create workspace config for tests."""
        base = WorkspaceConfig(
            session_id="docker-test",
            base_dir=tmp_path,
            cleanup_on_exit=True,
        )
        return IsolatedWorkspaceConfig(base_config=base)

    @pytest.mark.asyncio
    async def test_hardened_docker_lifecycle(self, config: IsolatedWorkspaceConfig) -> None:
        """Full lifecycle test with HardenedDockerWorkspace."""
        if not HardenedDockerWorkspace.is_available():
            pytest.skip("HardenedDockerWorkspace not available")

        async with HardenedDockerWorkspace.create(config) as workspace:
            # Workspace should be running
            assert workspace.is_running
            assert workspace.container_id is not None

            # Execute a simple command
            exit_code, stdout, _stderr = await HardenedDockerWorkspace.execute_command(
                workspace, ["echo", "hello"]
            )
            assert exit_code == 0
            assert "hello" in stdout

            # Health check should pass
            healthy = await HardenedDockerWorkspace.health_check(workspace)
            assert healthy

        # After context, should be terminated
        assert not workspace.is_running

    @pytest.mark.asyncio
    async def test_context_injection(self, config: IsolatedWorkspaceConfig, tmp_path: Path) -> None:
        """Test injecting context files into workspace."""
        if not HardenedDockerWorkspace.is_available():
            pytest.skip("HardenedDockerWorkspace not available")

        async with HardenedDockerWorkspace.create(config) as workspace:
            # Inject a context file
            files = [(tmp_path / "test.txt", b"Hello, World!")]
            await HardenedDockerWorkspace.inject_context(
                workspace,
                [(f.relative_to(tmp_path), f.read_bytes()) for f in files if f.exists()]
                if any(f.exists() for f in [f[0] for f in files])
                else files,
                metadata={"source": "test"},
            )

            # Verify context directory exists
            assert workspace.context_dir.exists()

    @pytest.mark.asyncio
    async def test_artifact_collection(self, config: IsolatedWorkspaceConfig) -> None:
        """Test collecting artifacts from workspace."""
        if not HardenedDockerWorkspace.is_available():
            pytest.skip("HardenedDockerWorkspace not available")

        async with HardenedDockerWorkspace.create(config) as workspace:
            # Create output directory and file
            workspace.output_dir.mkdir(parents=True, exist_ok=True)
            (workspace.output_dir / "result.txt").write_text("Success!")

            # Collect artifacts
            artifacts = await HardenedDockerWorkspace.collect_artifacts(workspace)

            # Should find our artifact
            assert len(artifacts) > 0
            paths = [str(p) for p, _ in artifacts]
            assert "result.txt" in paths


class TestRouterBackendFallback:
    """Tests for router fallback behavior."""

    def test_falls_back_when_preferred_unavailable(self) -> None:
        """Router should fall back to alternative backends."""
        router = WorkspaceRouter()

        with (
            patch.object(GVisorWorkspace, "is_available", return_value=False),
            patch.object(HardenedDockerWorkspace, "is_available", return_value=True),
        ):
            backend_class = router._get_available_backend_class(IsolationBackend.GVISOR)
            # Should fall back to HardenedDocker
            assert backend_class is HardenedDockerWorkspace

    def test_raises_when_no_backend_available(self) -> None:
        """Router should raise when no backend is available."""
        router = WorkspaceRouter()

        with (
            patch.object(GVisorWorkspace, "is_available", return_value=False),
            patch.object(HardenedDockerWorkspace, "is_available", return_value=False),
            patch.object(
                router.__class__,
                "BACKEND_CLASSES",
                {
                    IsolationBackend.GVISOR: GVisorWorkspace,
                    IsolationBackend.DOCKER_HARDENED: HardenedDockerWorkspace,
                },
            ),
            pytest.raises(RuntimeError, match="No isolation backend available"),
        ):
            router._get_available_backend_class(IsolationBackend.GVISOR)
