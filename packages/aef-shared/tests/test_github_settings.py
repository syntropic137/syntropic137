"""Tests for GitHubAppSettings.

Tests the GitHub App configuration with AEF_GITHUB_* environment variables.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from aef_shared.settings import Settings
from aef_shared.settings.github import GitHubAppSettings


class TestGitHubAppSettings:
    """Test GitHubAppSettings class."""

    def test_default_values(self) -> None:
        """Default values should be None (unconfigured)."""
        with patch.dict(os.environ, {}, clear=True):
            github = GitHubAppSettings(_env_file=None)

            assert github.app_id is None
            assert github.app_name is None
            assert github.installation_id is None
            assert github.private_key is None
            assert github.webhook_secret is None
            assert github.is_configured is False
            assert github.can_verify_webhooks is False
            assert github.bot_username is None
            assert github.bot_email is None

    def test_full_configuration(self) -> None:
        """Full configuration should work correctly."""
        env = {
            "AEF_GITHUB_APP_ID": "2461312",
            "AEF_GITHUB_APP_NAME": "aef-engineer-beta",
            "AEF_GITHUB_INSTALLATION_ID": "99311335",
            "AEF_GITHUB_PRIVATE_KEY": "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----",
            "AEF_GITHUB_WEBHOOK_SECRET": "supersecret123",
        }
        with patch.dict(os.environ, env, clear=True):
            github = GitHubAppSettings(_env_file=None)

            assert github.app_id == "2461312"
            assert github.app_name == "aef-engineer-beta"
            assert github.installation_id == "99311335"
            assert github.private_key is not None
            assert github.webhook_secret is not None
            assert github.is_configured is True
            assert github.can_verify_webhooks is True

    def test_bot_username(self) -> None:
        """Bot username should be formatted correctly."""
        env = {
            "AEF_GITHUB_APP_NAME": "aef-engineer-beta",
        }
        with patch.dict(os.environ, env, clear=True):
            github = GitHubAppSettings(_env_file=None)

            assert github.bot_username == "aef-engineer-beta[bot]"

    def test_bot_email(self) -> None:
        """Bot email should use GitHub noreply format."""
        # Need all required fields to avoid validation error
        env = {
            "AEF_GITHUB_APP_ID": "2461312",
            "AEF_GITHUB_APP_NAME": "aef-engineer-beta",
            "AEF_GITHUB_INSTALLATION_ID": "99311335",
            "AEF_GITHUB_PRIVATE_KEY": "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----",
        }
        with patch.dict(os.environ, env, clear=True):
            github = GitHubAppSettings(_env_file=None)

            assert github.bot_email == "2461312+aef-engineer-beta[bot]@users.noreply.github.com"

    def test_incomplete_config_fails(self) -> None:
        """Incomplete configuration should raise ValueError."""
        env = {
            "AEF_GITHUB_APP_ID": "12345",
            # Missing: INSTALLATION_ID and PRIVATE_KEY
        }
        with (
            patch.dict(os.environ, env, clear=True),
            pytest.raises(ValueError, match="Incomplete GitHub App configuration"),
        ):
            GitHubAppSettings(_env_file=None)

    def test_incomplete_config_two_of_three(self) -> None:
        """Two of three required fields should still fail."""
        env = {
            "AEF_GITHUB_APP_ID": "12345",
            "AEF_GITHUB_INSTALLATION_ID": "67890",
            # Missing: PRIVATE_KEY
        }
        with (
            patch.dict(os.environ, env, clear=True),
            pytest.raises(ValueError, match="AEF_GITHUB_PRIVATE_KEY"),
        ):
            GitHubAppSettings(_env_file=None)

    def test_all_or_nothing_config(self) -> None:
        """No config should be valid (for development)."""
        with patch.dict(os.environ, {}, clear=True):
            # Should not raise - empty config is valid
            github = GitHubAppSettings(_env_file=None)
            assert github.is_configured is False

    def test_settings_integration(self) -> None:
        """Main Settings should provide github property."""
        env = {
            "AEF_GITHUB_APP_ID": "12345",
            "AEF_GITHUB_APP_NAME": "test-app",
            "AEF_GITHUB_INSTALLATION_ID": "67890",
            "AEF_GITHUB_PRIVATE_KEY": "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)

            assert isinstance(settings.github, GitHubAppSettings)
            assert settings.github.app_id == "12345"
            assert settings.github.is_configured is True

    def test_private_key_secret(self) -> None:
        """Private key should be stored as SecretStr."""
        env = {
            "AEF_GITHUB_APP_ID": "12345",
            "AEF_GITHUB_INSTALLATION_ID": "67890",
            "AEF_GITHUB_PRIVATE_KEY": "secret-key-content",
        }
        with patch.dict(os.environ, env, clear=True):
            github = GitHubAppSettings(_env_file=None)

            # Should not expose in repr
            assert "secret-key-content" not in repr(github.private_key)
            # But should be accessible
            assert github.private_key.get_secret_value() == "secret-key-content"

    def test_webhook_secret_hidden(self) -> None:
        """Webhook secret should be stored as SecretStr."""
        env = {
            "AEF_GITHUB_WEBHOOK_SECRET": "my-webhook-secret",
        }
        with patch.dict(os.environ, env, clear=True):
            github = GitHubAppSettings(_env_file=None)

            # Should not expose in repr
            assert "my-webhook-secret" not in repr(github.webhook_secret)
            # But should be accessible
            assert github.webhook_secret.get_secret_value() == "my-webhook-secret"
