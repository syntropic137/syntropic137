"""Tests for HardenedDockerWorkspace.

These tests verify the hardened Docker workspace implementation.
HardenedDockerWorkspace inherits from GVisorWorkspace, so most
functionality is tested there - these tests focus on the differences.

See ADR-021: Isolated Workspace Architecture
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from aef_adapters.workspaces import GVisorWorkspace, HardenedDockerWorkspace
from aef_shared.settings import IsolationBackend, WorkspaceSecuritySettings

if TYPE_CHECKING:
    from pathlib import Path


class TestHardenedDockerWorkspaceClass:
    """Tests for HardenedDockerWorkspace class attributes."""

    def test_isolation_backend(self) -> None:
        """HardenedDockerWorkspace should have DOCKER_HARDENED backend."""
        assert HardenedDockerWorkspace.isolation_backend == IsolationBackend.DOCKER_HARDENED

    def test_inherits_from_gvisor_workspace(self) -> None:
        """HardenedDockerWorkspace should inherit from GVisorWorkspace."""
        assert issubclass(HardenedDockerWorkspace, GVisorWorkspace)

    def test_different_backend_than_gvisor(self) -> None:
        """Should have different isolation backend than GVisorWorkspace."""
        assert HardenedDockerWorkspace.isolation_backend != GVisorWorkspace.isolation_backend


class TestIsAvailable:
    """Tests for is_available() method."""

    @patch("shutil.which")
    def test_returns_true_when_docker_installed(self, mock_which: MagicMock) -> None:
        """Should return True when Docker is installed (no runsc needed)."""
        mock_which.return_value = "/usr/bin/docker"
        assert HardenedDockerWorkspace.is_available() is True

    @patch("shutil.which")
    def test_returns_false_when_docker_not_installed(self, mock_which: MagicMock) -> None:
        """Should return False when Docker is not installed."""
        mock_which.return_value = None
        assert HardenedDockerWorkspace.is_available() is False


class TestBuildDockerCommand:
    """Tests for _build_docker_command() method."""

    @pytest.fixture
    def security(self) -> WorkspaceSecuritySettings:
        """Create default security settings."""
        return WorkspaceSecuritySettings(_env_file=None)

    def test_does_not_include_runtime_flag(
        self, security: WorkspaceSecuritySettings, tmp_path: Path
    ) -> None:
        """Command should NOT include --runtime (uses default runc)."""
        cmd = HardenedDockerWorkspace._build_docker_command(
            container_name="test",
            workspace_dir=tmp_path,
            image="aef-workspace:latest",
            runtime="runsc",  # Should be ignored
            security=security,
            network="none",
        )
        assert "--runtime" not in cmd

    def test_includes_security_hardening(
        self, security: WorkspaceSecuritySettings, tmp_path: Path
    ) -> None:
        """Command should include security hardening options."""
        cmd = HardenedDockerWorkspace._build_docker_command(
            container_name="test",
            workspace_dir=tmp_path,
            image="aef-workspace:latest",
            runtime="ignored",
            security=security,
            network="none",
        )
        # Drop all capabilities
        assert "--cap-drop=ALL" in cmd
        # No new privileges
        assert "--security-opt=no-new-privileges:true" in cmd
        # AppArmor profile
        assert "--security-opt=apparmor=docker-default" in cmd

    def test_includes_resource_limits(
        self, security: WorkspaceSecuritySettings, tmp_path: Path
    ) -> None:
        """Command should include resource limits from security settings."""
        cmd = HardenedDockerWorkspace._build_docker_command(
            container_name="test",
            workspace_dir=tmp_path,
            image="aef-workspace:latest",
            runtime="ignored",
            security=security,
            network="none",
        )
        # Check memory limit
        assert "--memory" in cmd
        assert security.max_memory in cmd

        # Check CPU limit
        assert "--cpus" in cmd
        assert str(security.max_cpu) in cmd

        # Check pids limit
        assert "--pids-limit" in cmd
        assert str(security.max_pids) in cmd

    def test_includes_network_isolation(
        self, security: WorkspaceSecuritySettings, tmp_path: Path
    ) -> None:
        """Command should include network isolation."""
        cmd = HardenedDockerWorkspace._build_docker_command(
            container_name="test",
            workspace_dir=tmp_path,
            image="aef-workspace:latest",
            runtime="ignored",
            security=security,
            network="none",
        )
        assert "--network" in cmd
        idx = cmd.index("--network")
        assert cmd[idx + 1] == "none"

    def test_includes_read_only_with_tmpfs(
        self, security: WorkspaceSecuritySettings, tmp_path: Path
    ) -> None:
        """Command should include --read-only and tmpfs mounts."""
        assert security.read_only_root is True  # Default is True

        cmd = HardenedDockerWorkspace._build_docker_command(
            container_name="test",
            workspace_dir=tmp_path,
            image="aef-workspace:latest",
            runtime="ignored",
            security=security,
            network="none",
        )
        assert "--read-only" in cmd
        assert "--tmpfs" in cmd

    def test_command_differs_from_gvisor(
        self, security: WorkspaceSecuritySettings, tmp_path: Path
    ) -> None:
        """Command should differ from GVisorWorkspace (no --runtime)."""
        hardened_cmd = HardenedDockerWorkspace._build_docker_command(
            container_name="test",
            workspace_dir=tmp_path,
            image="aef-workspace:latest",
            runtime="runsc",
            security=security,
            network="none",
        )
        gvisor_cmd = GVisorWorkspace._build_docker_command(
            container_name="test",
            workspace_dir=tmp_path,
            image="aef-workspace:latest",
            runtime="runsc",
            security=security,
            network="none",
        )

        # GVisor should have --runtime, Hardened should not
        assert "--runtime" in gvisor_cmd
        assert "--runtime" not in hardened_cmd


class TestGetRuntimeName:
    """Tests for _get_runtime_name() method."""

    def test_returns_runc(self) -> None:
        """Should return 'runc' as the runtime name."""
        assert HardenedDockerWorkspace._get_runtime_name() == "runc"


class TestInheritedFunctionality:
    """Tests to verify inherited functionality works correctly."""

    def test_inherits_execute_command(self) -> None:
        """Should inherit execute_command from GVisorWorkspace."""
        assert hasattr(HardenedDockerWorkspace, "execute_command")
        # Should be the same underlying function (not overridden)
        assert (
            HardenedDockerWorkspace.execute_command.__func__
            is GVisorWorkspace.execute_command.__func__
        )

    def test_inherits_health_check(self) -> None:
        """Should inherit health_check from GVisorWorkspace."""
        assert hasattr(HardenedDockerWorkspace, "health_check")

    def test_inherits_create_isolation(self) -> None:
        """Should inherit _create_isolation from GVisorWorkspace."""
        assert hasattr(HardenedDockerWorkspace, "_create_isolation")

    def test_inherits_destroy_isolation(self) -> None:
        """Should inherit _destroy_isolation from GVisorWorkspace."""
        assert hasattr(HardenedDockerWorkspace, "_destroy_isolation")

    def test_inherits_inject_context(self) -> None:
        """Should inherit inject_context from BaseIsolatedWorkspace."""
        assert hasattr(HardenedDockerWorkspace, "inject_context")

    def test_inherits_collect_artifacts(self) -> None:
        """Should inherit collect_artifacts from BaseIsolatedWorkspace."""
        assert hasattr(HardenedDockerWorkspace, "collect_artifacts")
