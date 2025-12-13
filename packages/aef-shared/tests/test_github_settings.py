"""Tests for GitHubAppSettings."""

from __future__ import annotations

import os
from unittest import mock

import pytest
from pydantic import SecretStr

from aef_shared.settings.github import (
    GitHubAppSettings,
    reset_github_settings,
)


class TestGitHubAppSettings:
    """Tests for GitHubAppSettings."""

    def setup_method(self) -> None:
        """Reset settings before each test."""
        reset_github_settings()

    def test_defaults(self) -> None:
        """Test default values."""
        settings = GitHubAppSettings()

        assert settings.app_id == ""
        assert settings.app_name == "aef-app"
        assert settings.private_key.get_secret_value() == ""
        assert settings.installation_id == ""
        assert not settings.is_configured

    def test_is_configured(self) -> None:
        """Test is_configured property with complete config."""
        settings = GitHubAppSettings(
            app_id="123456",
            private_key=SecretStr(
                "-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
            ),
            installation_id="78901234",
        )

        assert settings.is_configured

    def test_unconfigured_is_valid(self) -> None:
        """Test that completely empty config is valid (unconfigured)."""
        settings = GitHubAppSettings()
        assert not settings.is_configured

    def test_partial_config_missing_app_id_raises_error(self) -> None:
        """Test that partial config (missing app_id) raises error."""
        with pytest.raises(ValueError, match="Incomplete GitHub App config"):
            GitHubAppSettings(
                private_key=SecretStr("key"),
                installation_id="123",
            )

    def test_partial_config_missing_private_key_raises_error(self) -> None:
        """Test that partial config (missing private_key) raises error."""
        with pytest.raises(ValueError, match="Incomplete GitHub App config"):
            GitHubAppSettings(
                app_id="123456",
                installation_id="123",
            )

    def test_partial_config_missing_installation_id_raises_error(self) -> None:
        """Test that partial config (missing installation_id) raises error."""
        with pytest.raises(ValueError, match="Incomplete GitHub App config"):
            GitHubAppSettings(
                app_id="123456",
                private_key=SecretStr("key"),
            )

    def test_bot_name_default(self) -> None:
        """Test bot_name property with default app_name."""
        settings = GitHubAppSettings()
        assert settings.bot_name == "aef-app[bot]"

    def test_bot_name_with_complete_config(self) -> None:
        """Test bot_name property with complete config."""
        settings = GitHubAppSettings(
            app_id="123456",
            app_name="my-app",
            private_key=SecretStr("key"),
            installation_id="789",
        )
        assert settings.bot_name == "my-app[bot]"

    def test_bot_email_with_complete_config(self) -> None:
        """Test bot_email property with complete config."""
        settings = GitHubAppSettings(
            app_id="123456",
            app_name="my-app",
            private_key=SecretStr("key"),
            installation_id="789",
        )
        assert settings.bot_email == "123456+my-app[bot]@users.noreply.github.com"

    def test_env_prefix(self) -> None:
        """Test that settings use correct env prefix."""
        with mock.patch.dict(
            os.environ,
            {
                "AEF_GITHUB_APP_ID": "999",
                "AEF_GITHUB_APP_NAME": "test-app",
                "AEF_GITHUB_PRIVATE_KEY": "secret-key",
                "AEF_GITHUB_INSTALLATION_ID": "888",
            },
        ):
            reset_github_settings()
            settings = GitHubAppSettings()

            assert settings.app_id == "999"
            assert settings.app_name == "test-app"
            assert settings.private_key.get_secret_value() == "secret-key"
            assert settings.installation_id == "888"
