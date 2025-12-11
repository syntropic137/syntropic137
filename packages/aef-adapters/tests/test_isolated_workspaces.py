"""Tests for isolated workspace protocol and types.

See ADR-021: Isolated Workspace Architecture
"""

from pathlib import Path

import pytest

from aef_adapters.agents.agentic_types import WorkspaceConfig
from aef_adapters.workspaces import (
    BaseIsolatedWorkspace,
    IsolatedWorkspace,
    IsolatedWorkspaceConfig,
    IsolatedWorkspaceProtocol,
)
from aef_shared.settings import (
    IsolationBackend,
    WorkspaceSecuritySettings,
)


class TestIsolatedWorkspace:
    """Tests for IsolatedWorkspace dataclass."""

    @pytest.fixture
    def base_config(self, tmp_path: Path) -> WorkspaceConfig:
        """Create a base workspace config."""
        return WorkspaceConfig(
            session_id="test-isolated",
            base_dir=tmp_path,
        )

    @pytest.fixture
    def isolated_workspace(self, base_config: WorkspaceConfig, tmp_path: Path) -> IsolatedWorkspace:
        """Create an isolated workspace for testing."""
        return IsolatedWorkspace(
            path=tmp_path / "workspace",
            config=base_config,
            isolation_backend=IsolationBackend.GVISOR,
            container_id="test-container-123",
        )

    def test_basic_properties(self, isolated_workspace: IsolatedWorkspace) -> None:
        """IsolatedWorkspace should have expected properties."""
        assert isolated_workspace.isolation_backend == IsolationBackend.GVISOR
        assert isolated_workspace.container_id == "test-container-123"
        assert isolated_workspace.vm_id is None
        assert isolated_workspace.sandbox_id is None

    def test_path_properties(self, isolated_workspace: IsolatedWorkspace, tmp_path: Path) -> None:
        """IsolatedWorkspace should have correct path properties."""
        ws = isolated_workspace
        base = tmp_path / "workspace"

        assert ws.context_dir == base / ".context"
        assert ws.output_dir == base / "output"
        assert ws.hooks_dir == base / ".claude" / "hooks"
        assert ws.analytics_path == base / ".agentic" / "analytics" / "events.jsonl"

    def test_isolation_id(self, base_config: WorkspaceConfig, tmp_path: Path) -> None:
        """isolation_id should return the first available ID."""
        # Container ID
        ws_container = IsolatedWorkspace(
            path=tmp_path / "ws1",
            config=base_config,
            isolation_backend=IsolationBackend.GVISOR,
            container_id="container-123",
        )
        assert ws_container.isolation_id == "container-123"

        # VM ID
        ws_vm = IsolatedWorkspace(
            path=tmp_path / "ws2",
            config=base_config,
            isolation_backend=IsolationBackend.FIRECRACKER,
            vm_id="vm-456",
        )
        assert ws_vm.isolation_id == "vm-456"

        # Sandbox ID
        ws_sandbox = IsolatedWorkspace(
            path=tmp_path / "ws3",
            config=base_config,
            isolation_backend=IsolationBackend.CLOUD,
            sandbox_id="sandbox-789",
        )
        assert ws_sandbox.isolation_id == "sandbox-789"

    def test_lifecycle_timestamps(self, isolated_workspace: IsolatedWorkspace) -> None:
        """Lifecycle timestamps should track workspace state."""
        ws = isolated_workspace

        # Initially not started
        assert ws.started_at is None
        assert ws.terminated_at is None
        assert not ws.is_running
        assert ws.duration_seconds is None

        # Mark started
        ws.mark_started()
        assert ws.started_at is not None
        assert ws.is_running
        assert ws.duration_seconds is not None
        assert ws.duration_seconds >= 0

        # Mark terminated
        ws.mark_terminated()
        assert ws.terminated_at is not None
        assert not ws.is_running
        assert ws.duration_seconds is not None

    def test_resource_usage_tracking(self, isolated_workspace: IsolatedWorkspace) -> None:
        """Resource usage should be trackable."""
        ws = isolated_workspace

        # Initial values
        assert ws.memory_used_bytes == 0
        assert ws.cpu_time_seconds == 0.0
        assert ws.network_bytes_in == 0
        assert ws.network_bytes_out == 0

        # Update values
        ws.update_resource_usage(
            memory_bytes=1024 * 1024 * 256,  # 256 MB
            cpu_seconds=5.5,
            network_in=1024,
            network_out=512,
        )

        assert ws.memory_used_bytes == 256 * 1024 * 1024
        assert ws.cpu_time_seconds == 5.5
        assert ws.network_bytes_in == 1024
        assert ws.network_bytes_out == 512


class TestIsolatedWorkspaceConfig:
    """Tests for IsolatedWorkspaceConfig."""

    @pytest.fixture
    def base_config(self, tmp_path: Path) -> WorkspaceConfig:
        """Create a base workspace config."""
        return WorkspaceConfig(
            session_id="test-session",
            base_dir=tmp_path,
            workflow_id="wf-123",
            phase_id="phase-1",
        )

    def test_delegates_to_base_config(self, base_config: WorkspaceConfig) -> None:
        """IsolatedWorkspaceConfig should delegate to base config."""
        isolated_config = IsolatedWorkspaceConfig(base_config=base_config)

        assert isolated_config.session_id == "test-session"
        assert isolated_config.workflow_id == "wf-123"
        assert isolated_config.phase_id == "phase-1"

    def test_accepts_security_settings(self, base_config: WorkspaceConfig) -> None:
        """IsolatedWorkspaceConfig should accept security settings."""
        security = WorkspaceSecuritySettings(_env_file=None)
        isolated_config = IsolatedWorkspaceConfig(
            base_config=base_config,
            security=security,
        )

        assert isolated_config.security is not None
        assert isolated_config.security.allow_network is False

    def test_accepts_isolation_backend_override(self, base_config: WorkspaceConfig) -> None:
        """IsolatedWorkspaceConfig should accept backend override."""
        isolated_config = IsolatedWorkspaceConfig(
            base_config=base_config,
            isolation_backend=IsolationBackend.FIRECRACKER,
        )

        assert isolated_config.isolation_backend == IsolationBackend.FIRECRACKER


class TestWorkspaceProtocol:
    """Tests for WorkspaceProtocol compliance."""

    def test_local_workspace_implements_protocol(self) -> None:
        """LocalWorkspace should implement WorkspaceProtocol."""
        from aef_adapters.workspaces import LocalWorkspace

        assert isinstance(LocalWorkspace, type)
        # Check required methods exist
        assert hasattr(LocalWorkspace, "create")
        assert hasattr(LocalWorkspace, "inject_context")
        assert hasattr(LocalWorkspace, "collect_artifacts")


class TestIsolatedWorkspaceProtocol:
    """Tests for IsolatedWorkspaceProtocol."""

    def test_protocol_defines_required_attributes(self) -> None:
        """IsolatedWorkspaceProtocol should define required attributes."""
        # Check protocol is a Protocol
        assert hasattr(IsolatedWorkspaceProtocol, "__protocol_attrs__") or hasattr(
            IsolatedWorkspaceProtocol, "_is_protocol"
        )

    def test_base_isolated_workspace_has_required_methods(self) -> None:
        """BaseIsolatedWorkspace should have required protocol methods."""
        # Check all protocol methods exist
        assert hasattr(BaseIsolatedWorkspace, "create")
        assert hasattr(BaseIsolatedWorkspace, "inject_context")
        assert hasattr(BaseIsolatedWorkspace, "collect_artifacts")
        assert hasattr(BaseIsolatedWorkspace, "health_check")
        assert hasattr(BaseIsolatedWorkspace, "execute_command")
        assert hasattr(BaseIsolatedWorkspace, "is_available")

    def test_base_isolated_workspace_is_abstract(self) -> None:
        """BaseIsolatedWorkspace should be abstract (cannot instantiate)."""
        # ABC should not be directly instantiable due to abstract methods
        assert hasattr(BaseIsolatedWorkspace, "__abstractmethods__")
        assert len(BaseIsolatedWorkspace.__abstractmethods__) > 0


class TestSecuritySettingsIntegration:
    """Tests for security settings integration with workspaces."""

    def test_default_security_is_restrictive(self) -> None:
        """Default security settings should be maximally restrictive."""
        security = WorkspaceSecuritySettings(_env_file=None)

        # Network isolated
        assert security.allow_network is False
        assert security.get_allowed_hosts_list() == []

        # Filesystem protected
        assert security.read_only_root is True
        assert security.max_workspace_size == "1Gi"

        # Resource limits
        assert security.max_memory == "512Mi"
        assert security.max_cpu == 0.5
        assert security.max_pids == 100
        assert security.max_execution_time == 3600

    def test_isolated_workspace_stores_security(self, tmp_path: Path) -> None:
        """IsolatedWorkspace should store security settings."""
        config = WorkspaceConfig(
            session_id="test",
            base_dir=tmp_path,
        )
        security = WorkspaceSecuritySettings(_env_file=None)

        workspace = IsolatedWorkspace(
            path=tmp_path / "ws",
            config=config,
            isolation_backend=IsolationBackend.GVISOR,
            security=security,
        )

        assert workspace.security is not None
        assert workspace.security.allow_network is False
