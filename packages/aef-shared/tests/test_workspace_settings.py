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
    ContainerLoggingSettings,
    GitCredentialType,
    GitIdentityResolver,
    GitIdentitySettings,
    IsolationBackend,
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


@pytest.mark.integration
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
            assert settings.docker_image == "aef-workspace-claude:latest"
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
    """Test workspace settings integration with main Settings class.

    Note: We test WorkspaceSettings directly with _env_file=None to isolate
    from real .env file values during testing.
    """

    def test_workspace_settings_creation(self) -> None:
        """WorkspaceSettings should be creatable with defaults."""
        with patch.dict(os.environ, {}, clear=True):
            workspace = WorkspaceSettings(_env_file=None)
            assert isinstance(workspace, WorkspaceSettings)

    def test_workspace_security_settings_creation(self) -> None:
        """WorkspaceSecuritySettings should be creatable with defaults."""
        with patch.dict(os.environ, {}, clear=True):
            security = WorkspaceSecuritySettings(_env_file=None)
            assert isinstance(security, WorkspaceSecuritySettings)

    def test_workspace_respects_env_vars(self) -> None:
        """Workspace settings should respect env vars."""
        env = {
            "AEF_WORKSPACE_POOL_SIZE": "200",
            "AEF_SECURITY_MAX_MEMORY": "1Gi",
        }
        with patch.dict(os.environ, env, clear=True):
            workspace = WorkspaceSettings(_env_file=None)
            security = WorkspaceSecuritySettings(_env_file=None)

            assert workspace.pool_size == 200
            assert security.max_memory == "1Gi"


# =============================================================================
# Git Identity Settings Tests
# =============================================================================


class TestGitIdentitySettings:
    """Test GitIdentitySettings class."""

    def test_default_values(self) -> None:
        """Default values should be None (unconfigured)."""
        with patch.dict(os.environ, {}, clear=True):
            git = GitIdentitySettings(_env_file=None)

            assert git.user_name is None
            assert git.user_email is None
            assert git.token is None
            # NOTE: github_app_* fields moved to GitHubAppSettings (AEF_GITHUB_* prefix)
            assert git.is_configured is False
            assert git.has_credentials is False
            assert git.credential_type == GitCredentialType.NONE

    def test_identity_from_env(self) -> None:
        """Git identity should load from environment variables."""
        env = {
            "AEF_GIT_USER_NAME": "aef-bot[bot]",
            "AEF_GIT_USER_EMAIL": "bot@aef.dev",
        }
        with patch.dict(os.environ, env, clear=True):
            git = GitIdentitySettings(_env_file=None)

            assert git.user_name == "aef-bot[bot]"
            assert git.user_email == "bot@aef.dev"
            assert git.is_configured is True
            assert git.has_credentials is False
            assert git.credential_type == GitCredentialType.NONE

    def test_https_credentials(self) -> None:
        """HTTPS token should be detected as credential type."""
        env = {
            "AEF_GIT_USER_NAME": "test-user",
            "AEF_GIT_USER_EMAIL": "test@example.com",
            "AEF_GIT_TOKEN": "ghp_test123token",
        }
        with patch.dict(os.environ, env, clear=True):
            git = GitIdentitySettings(_env_file=None)

            assert git.token is not None
            assert git.token.get_secret_value() == "ghp_test123token"
            assert git.has_credentials is True
            assert git.credential_type == GitCredentialType.HTTPS

    def test_github_app_credentials(self) -> None:
        """GitHub App (AEF_GITHUB_*) should be preferred over HTTPS token."""
        from aef_shared.settings.github import GitHubAppSettings

        env = {
            "AEF_GIT_USER_NAME": "test-user",
            "AEF_GIT_USER_EMAIL": "test@example.com",
            "AEF_GIT_TOKEN": "ghp_test123token",
            # GitHub App uses separate AEF_GITHUB_* prefix
            "AEF_GITHUB_APP_ID": "12345",
            "AEF_GITHUB_INSTALLATION_ID": "67890",
            "AEF_GITHUB_PRIVATE_KEY": "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----",
        }
        with patch.dict(os.environ, env, clear=True):
            git = GitIdentitySettings(_env_file=None)
            github = GitHubAppSettings(_env_file=None)

            # GitIdentitySettings should detect GitHub App is configured
            assert git.credential_type == GitCredentialType.GITHUB_APP
            # GitHub App settings are in separate class
            assert github.app_id == "12345"
            assert github.installation_id == "67890"
            assert github.is_configured is True

    def test_incomplete_github_app_fails_validation(self) -> None:
        """Incomplete GitHub App config should raise ValueError."""
        from aef_shared.settings.github import GitHubAppSettings

        env = {
            "AEF_GITHUB_APP_ID": "12345",
            # Missing: INSTALLATION_ID and PRIVATE_KEY
        }
        with (
            patch.dict(os.environ, env, clear=True),
            pytest.raises(ValueError, match="Incomplete GitHub App config"),
        ):
            GitHubAppSettings(_env_file=None)

    def test_settings_integration(self) -> None:
        """GitIdentitySettings should work with env vars."""
        env = {
            "AEF_GIT_USER_NAME": "agent",
            "AEF_GIT_USER_EMAIL": "agent@aef.dev",
        }
        with patch.dict(os.environ, env, clear=True):
            git_identity = GitIdentitySettings(_env_file=None)

            assert git_identity.user_name == "agent"
            assert git_identity.user_email == "agent@aef.dev"


# =============================================================================
# Container Logging Settings Tests
# =============================================================================


class TestContainerLoggingSettings:
    """Test ContainerLoggingSettings class."""

    def test_default_values(self) -> None:
        """Default values should be sensible for production."""
        with patch.dict(os.environ, {}, clear=True):
            logging = ContainerLoggingSettings(_env_file=None)

            assert logging.level == "INFO"
            assert logging.format == "json"
            assert logging.log_commands is True
            assert logging.log_tool_calls is True
            assert logging.log_api_calls is False
            assert logging.redact_secrets is True
            assert logging.log_file_path == "/workspace/.logs/agent.jsonl"
            assert logging.max_log_size_mb == 10

    def test_environment_override(self) -> None:
        """Environment variables should override defaults."""
        env = {
            "AEF_LOGGING_LEVEL": "DEBUG",
            "AEF_LOGGING_FORMAT": "text",
            "AEF_LOGGING_LOG_API_CALLS": "true",
        }
        with patch.dict(os.environ, env, clear=True):
            logging = ContainerLoggingSettings(_env_file=None)

            assert logging.level == "DEBUG"
            assert logging.format == "text"
            assert logging.log_api_calls is True

    def test_secret_redaction(self) -> None:
        """redact() should remove sensitive patterns."""
        with patch.dict(os.environ, {}, clear=True):
            logging = ContainerLoggingSettings(_env_file=None)

            # Anthropic API key
            result = logging.redact("key=sk-ant-api03-1234567890")
            assert "[REDACTED]" in result
            assert "sk-ant" not in result

            # GitHub PAT (classic)
            result = logging.redact("token=ghp_1234567890abcdef")
            assert "[REDACTED]" in result
            assert "ghp_" not in result

            # GitHub PAT (fine-grained)
            result = logging.redact("token=github_pat_123_abc")
            assert "[REDACTED]" in result

            # Password in URL
            result = logging.redact("postgres://user:password=secret&host=db")
            assert "[REDACTED]" in result
            assert "secret" not in result

            # Bearer token
            result = logging.redact("Authorization: Bearer eyJhbGc.ey.sig")
            assert "[REDACTED]" in result
            assert "eyJhbGc" not in result

    def test_redaction_disabled(self) -> None:
        """Redaction should be skippable (for debugging)."""
        env = {
            "AEF_LOGGING_REDACT_SECRETS": "false",
        }
        with patch.dict(os.environ, env, clear=True):
            logging = ContainerLoggingSettings(_env_file=None)

            result = logging.redact("key=sk-ant-api03-1234567890")
            assert "sk-ant-api03-1234567890" in result  # NOT redacted

    def test_settings_integration(self) -> None:
        """ContainerLoggingSettings should work with defaults."""
        with patch.dict(os.environ, {}, clear=True):
            logging = ContainerLoggingSettings(_env_file=None)

            assert isinstance(logging, ContainerLoggingSettings)
            assert logging.level == "INFO"


# =============================================================================
# Git Identity Resolver Tests
# =============================================================================


class TestGitIdentityResolver:
    """Test GitIdentityResolver class."""

    def test_workflow_override_takes_precedence(self) -> None:
        """Workflow override should take precedence over env vars."""
        env = {
            "AEF_GIT_USER_NAME": "env-user",
            "AEF_GIT_USER_EMAIL": "env@example.com",
        }
        override = GitIdentitySettings(
            user_name="workflow-user",
            user_email="workflow@example.com",
        )

        with patch.dict(os.environ, env, clear=True):
            resolver = GitIdentityResolver()
            result = resolver.resolve(workflow_override=override)

            assert result.user_name == "workflow-user"
            assert result.user_email == "workflow@example.com"

    def test_env_vars_used_when_no_override(self) -> None:
        """Environment variables should be used when no override."""
        env = {
            "AEF_GIT_USER_NAME": "env-user",
            "AEF_GIT_USER_EMAIL": "env@example.com",
        }

        with patch.dict(os.environ, env, clear=True):
            resolver = GitIdentityResolver()
            result = resolver.resolve()

            assert result.user_name == "env-user"
            assert result.user_email == "env@example.com"

    def test_local_git_config_in_development(self) -> None:
        """Local git config should be used in development mode."""
        env = {
            "APP_ENVIRONMENT": "development",
        }

        with patch.dict(os.environ, env, clear=True):
            resolver = GitIdentityResolver()

            # Mock subprocess to return git config values
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = [
                    type("Result", (), {"returncode": 0, "stdout": "Local User\n"})(),
                    type("Result", (), {"returncode": 0, "stdout": "local@dev.com\n"})(),
                ]

                result = resolver.resolve()

                assert result.user_name == "Local User"
                assert result.user_email == "local@dev.com"

    def test_raises_when_not_configured_in_production(self) -> None:
        """Should raise ValueError when not configured in production."""
        env = {
            "APP_ENVIRONMENT": "production",
        }

        with patch.dict(os.environ, env, clear=True):
            resolver = GitIdentityResolver()

            with pytest.raises(ValueError, match="Git identity not configured"):
                resolver.resolve()

    def test_incomplete_override_falls_back(self) -> None:
        """Incomplete override should fall back to env vars."""
        env = {
            "AEF_GIT_USER_NAME": "env-user",
            "AEF_GIT_USER_EMAIL": "env@example.com",
        }
        # Override with only name, no email
        override = GitIdentitySettings(user_name="partial-user")

        with patch.dict(os.environ, env, clear=True):
            resolver = GitIdentityResolver()
            result = resolver.resolve(workflow_override=override)

            # Falls back to env since override is incomplete
            assert result.user_name == "env-user"
            assert result.user_email == "env@example.com"
