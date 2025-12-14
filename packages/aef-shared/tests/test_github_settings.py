"""Tests for GitHubAppSettings."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from aef_shared.settings.github import (
    GitHubAppSettings,
    reset_github_settings,
)


class TestGitHubAppSettings:
    """Tests for GitHubAppSettings.

    Note: These tests explicitly set values rather than relying on defaults,
    since GitHubAppSettings reads from .env file which may have real values.
    """

    def teardown_method(self) -> None:
        """Reset settings after each test."""
        reset_github_settings()

    def test_is_configured_with_complete_config(self) -> None:
        """Test is_configured property with complete config."""
        settings = GitHubAppSettings(
            app_id="123456",
            private_key=SecretStr(
                "-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
            ),
            installation_id="78901234",
            _env_file=None,  # Don't read from .env
        )

        assert settings.is_configured

    def test_unconfigured_with_empty_values(self) -> None:
        """Test that explicitly empty config is not configured."""
        settings = GitHubAppSettings(
            app_id="",
            private_key=SecretStr(""),
            installation_id="",
            _env_file=None,
        )
        assert not settings.is_configured

    def test_partial_config_missing_app_id_raises_error(self) -> None:
        """Test that partial config (missing app_id) raises error."""
        with pytest.raises(ValueError, match="Incomplete GitHub App config"):
            GitHubAppSettings(
                app_id="",  # Empty
                private_key=SecretStr("key"),
                installation_id="123",
                _env_file=None,
            )

    def test_partial_config_missing_private_key_raises_error(self) -> None:
        """Test that partial config (missing private_key) raises error."""
        with pytest.raises(ValueError, match="Incomplete GitHub App config"):
            GitHubAppSettings(
                app_id="123456",
                private_key=SecretStr(""),  # Empty
                installation_id="123",
                _env_file=None,
            )

    def test_partial_config_missing_installation_id_raises_error(self) -> None:
        """Test that partial config (missing installation_id) raises error."""
        with pytest.raises(ValueError, match="Incomplete GitHub App config"):
            GitHubAppSettings(
                app_id="123456",
                private_key=SecretStr("key"),
                installation_id="",  # Empty
                _env_file=None,
            )

    def test_bot_name_property(self) -> None:
        """Test bot_name property with explicit app_name."""
        settings = GitHubAppSettings(
            app_id="123456",
            app_name="my-app",
            private_key=SecretStr("key"),
            installation_id="789",
            _env_file=None,
        )
        assert settings.bot_name == "my-app[bot]"

    def test_bot_name_default(self) -> None:
        """Test bot_name property with default app_name."""
        settings = GitHubAppSettings(
            app_id="",
            app_name="aef-app",  # Explicit default
            private_key=SecretStr(""),
            installation_id="",
            _env_file=None,
        )
        assert settings.bot_name == "aef-app[bot]"

    def test_bot_email_with_complete_config(self) -> None:
        """Test bot_email property with complete config."""
        settings = GitHubAppSettings(
            app_id="123456",
            app_name="my-app",
            private_key=SecretStr("key"),
            installation_id="789",
            _env_file=None,
        )
        assert settings.bot_email == "123456+my-app[bot]@users.noreply.github.com"

    def test_fully_configured_settings(self) -> None:
        """Test a fully configured settings object."""
        settings = GitHubAppSettings(
            app_id="999",
            app_name="test-app",
            private_key=SecretStr("secret-key"),
            installation_id="888",
            _env_file=None,
        )

        assert settings.app_id == "999"
        assert settings.app_name == "test-app"
        assert settings.private_key.get_secret_value() == "secret-key"
        assert settings.installation_id == "888"
        assert settings.is_configured
