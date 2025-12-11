"""Tests for workspace isolation settings.

See ADR-021: Isolated Workspace Architecture
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from aef_shared.settings import (
    CloudProvider,
    IsolationBackend,
    Settings,
    WorkspaceSecuritySettings,
    WorkspaceSettings,
    get_default_isolation_backend,
    reset_settings,
)


@pytest.fixture(autouse=True)
def reset_settings_cache() -> None:
    """Reset settings cache before and after each test."""
    reset_settings()
    yield
    reset_settings()


class TestIsolationBackend:
    """Test IsolationBackend enum."""

    def test_all_backends_defined(self) -> None:
        """All expected isolation backends should be defined."""
        assert IsolationBackend.FIRECRACKER == "firecracker"
        assert IsolationBackend.KATA == "kata"
        assert IsolationBackend.GVISOR == "gvisor"
        assert IsolationBackend.DOCKER_HARDENED == "docker_hardened"
        assert IsolationBackend.CLOUD == "cloud"

    def test_backend_count(self) -> None:
        """Should have exactly 5 backends."""
        assert len(IsolationBackend) == 5


class TestCloudProvider:
    """Test CloudProvider enum."""

    def test_all_providers_defined(self) -> None:
        """All expected cloud providers should be defined."""
        assert CloudProvider.E2B == "e2b"
        assert CloudProvider.MODAL == "modal"


class TestWorkspaceSecuritySettings:
    """Test WorkspaceSecuritySettings class."""

    def test_default_values_are_restrictive(self) -> None:
        """Default values should be maximally restrictive."""
        with patch.dict(os.environ, {}, clear=True):
            security = WorkspaceSecuritySettings(_env_file=None)

            # Network isolated by default
            assert security.allow_network is False
            assert security.allowed_hosts == ""
            assert security.get_allowed_hosts_list() == []

            # Filesystem protected
            assert security.read_only_root is True
            assert security.max_workspace_size == "1Gi"

            # Resource limits set
            assert security.max_memory == "512Mi"
            assert security.max_cpu == 0.5
            assert security.max_pids == 100
            assert security.max_execution_time == 3600

    def test_environment_override(self) -> None:
        """Environment variables should override defaults."""
        env = {
            "AEF_SECURITY_ALLOW_NETWORK": "true",
            "AEF_SECURITY_MAX_MEMORY": "2Gi",
            "AEF_SECURITY_MAX_CPU": "2.0",
            "AEF_SECURITY_MAX_PIDS": "500",
        }
        with patch.dict(os.environ, env, clear=True):
            security = WorkspaceSecuritySettings(_env_file=None)

            assert security.allow_network is True
            assert security.max_memory == "2Gi"
            assert security.max_cpu == 2.0
            assert security.max_pids == 500

    def test_allowed_hosts_comma_format(self) -> None:
        """allowed_hosts should parse comma-separated format."""
        env = {
            "AEF_SECURITY_ALLOWED_HOSTS": "pypi.org, api.github.com",
        }
        with patch.dict(os.environ, env, clear=True):
            security = WorkspaceSecuritySettings(_env_file=None)

            assert security.allowed_hosts == "pypi.org, api.github.com"
            assert security.get_allowed_hosts_list() == ["pypi.org", "api.github.com"]

    def test_allowed_hosts_empty_string(self) -> None:
        """allowed_hosts should handle empty string."""
        env = {
            "AEF_SECURITY_ALLOWED_HOSTS": "",
        }
        with patch.dict(os.environ, env, clear=True):
            security = WorkspaceSecuritySettings(_env_file=None)

            assert security.allowed_hosts == ""
            assert security.get_allowed_hosts_list() == []


class TestWorkspaceSettings:
    """Test WorkspaceSettings class."""

    def test_default_values(self) -> None:
        """Default values should be reasonable for production."""
        with patch.dict(os.environ, {}, clear=True):
            settings = WorkspaceSettings(_env_file=None)

            # Capacity defaults
            assert settings.pool_size == 100
            assert settings.max_concurrent == 1000

            # Cloud overflow enabled by default
            assert settings.enable_cloud_overflow is True
            assert settings.cloud_provider == CloudProvider.E2B
            assert settings.cloud_api_key is None

            # Docker settings
            assert settings.docker_image == "aef-workspace:latest"
            assert settings.docker_runtime == "runsc"
            assert settings.docker_network == "none"

    def test_isolation_backend_override(self) -> None:
        """isolation_backend should be overridable via env."""
        env = {
            "AEF_WORKSPACE_ISOLATION_BACKEND": "docker_hardened",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = WorkspaceSettings(_env_file=None)

            assert settings.isolation_backend == IsolationBackend.DOCKER_HARDENED

    def test_cloud_settings_override(self) -> None:
        """Cloud settings should be overridable via env."""
        env = {
            "AEF_WORKSPACE_CLOUD_PROVIDER": "modal",
            "AEF_WORKSPACE_CLOUD_API_KEY": "secret-key",
            "AEF_WORKSPACE_CLOUD_TEMPLATE": "custom-template",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = WorkspaceSettings(_env_file=None)

            assert settings.cloud_provider == CloudProvider.MODAL
            assert settings.cloud_api_key is not None
            assert settings.cloud_api_key.get_secret_value() == "secret-key"
            assert settings.cloud_template == "custom-template"

    def test_capacity_limits(self) -> None:
        """Capacity settings should accept reasonable values."""
        env = {
            "AEF_WORKSPACE_POOL_SIZE": "500",
            "AEF_WORKSPACE_MAX_CONCURRENT": "5000",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = WorkspaceSettings(_env_file=None)

            assert settings.pool_size == 500
            assert settings.max_concurrent == 5000


class TestGetDefaultIsolationBackend:
    """Test get_default_isolation_backend function."""

    def test_returns_isolation_backend(self) -> None:
        """Should return an IsolationBackend enum value."""
        backend = get_default_isolation_backend()
        assert isinstance(backend, IsolationBackend)

    @patch("sys.platform", "linux")
    @patch("shutil.which")
    def test_linux_with_firecracker(self, mock_which: patch) -> None:
        """Linux with KVM and Firecracker should use Firecracker."""
        mock_which.return_value = "/usr/bin/firecracker"

        with patch.object(Path, "exists", return_value=True):
            backend = get_default_isolation_backend()
            # If firecracker is available, should return FIRECRACKER
            assert backend == IsolationBackend.FIRECRACKER

    @patch("sys.platform", "darwin")
    @patch("shutil.which")
    def test_macos_uses_gvisor_fallback(self, mock_which: patch) -> None:
        """macOS should fall back to gVisor."""
        mock_which.return_value = "/usr/local/bin/docker"

        backend = get_default_isolation_backend()
        # macOS can't use Firecracker, should fall back to GVISOR
        assert backend == IsolationBackend.GVISOR


class TestSettingsWorkspaceIntegration:
    """Test workspace settings integration with main Settings class."""

    def test_workspace_property(self) -> None:
        """Settings.workspace should return WorkspaceSettings."""
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)

            workspace = settings.workspace
            assert isinstance(workspace, WorkspaceSettings)

    def test_workspace_security_property(self) -> None:
        """Settings.workspace_security should return WorkspaceSecuritySettings."""
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)

            security = settings.workspace_security
            assert isinstance(security, WorkspaceSecuritySettings)

    def test_workspace_respects_env_vars(self) -> None:
        """Workspace settings from main Settings should respect env vars."""
        env = {
            "AEF_WORKSPACE_POOL_SIZE": "200",
            "AEF_SECURITY_MAX_MEMORY": "1Gi",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)

            assert settings.workspace.pool_size == 200
            assert settings.workspace_security.max_memory == "1Gi"
