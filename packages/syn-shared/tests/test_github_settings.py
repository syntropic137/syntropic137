"""Tests for GitHubAppSettings."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pydantic import SecretStr

from syn_shared.settings.github import (
    GitHubAppSettings,
    reset_github_settings,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
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

    def test_app_id_and_private_key_without_installation_id_is_valid(self) -> None:
        """Test that app_id + private_key without installation_id is fully configured.

        installation_id is optional — installations are discovered dynamically
        from webhook payloads for multi-org/multi-account support.
        """
        settings = GitHubAppSettings(
            app_id="123456",
            private_key=SecretStr("key"),
            installation_id="",  # Not required
            _env_file=None,
        )
        assert settings.is_configured

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
            app_name="syn-app",  # Explicit default
            private_key=SecretStr(""),
            installation_id="",
            _env_file=None,
        )
        assert settings.bot_name == "syn-app[bot]"

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
            _env_file=None,
        )

        assert settings.app_id == "999"
        assert settings.app_name == "test-app"
        assert settings.private_key.get_secret_value() == "secret-key"
        assert settings.is_configured

    # =========================================================================
    # FILE-BASED KEY (app_private_key_file) — Docker secret path
    # =========================================================================

    def test_is_configured_with_key_file(self, tmp_path: Path) -> None:
        """app_id + non-empty key file = configured."""
        pem = tmp_path / "key.pem"
        pem.write_text("-----BEGIN RSA PRIVATE KEY-----\ndata\n-----END RSA PRIVATE KEY-----")

        settings = GitHubAppSettings(
            app_id="123",
            private_key=SecretStr(""),
            app_private_key_file=str(pem),
            _env_file=None,
        )
        assert settings.is_configured
        assert settings._has_usable_key_file

    def test_empty_placeholder_file_not_configured(self, tmp_path: Path) -> None:
        """Empty placeholder (Docker secret for unconfigured app) should not count."""
        pem = tmp_path / "key.pem"
        pem.touch()  # 0 bytes — empty placeholder

        settings = GitHubAppSettings(
            app_id="",
            private_key=SecretStr(""),
            app_private_key_file=str(pem),
            _env_file=None,
        )
        assert not settings.is_configured
        assert not settings._has_usable_key_file

    def test_nonexistent_key_file_not_configured(self) -> None:
        """Nonexistent file path should not count as configured."""
        settings = GitHubAppSettings(
            app_id="",
            private_key=SecretStr(""),
            app_private_key_file="/run/secrets/github_app_private_key",
            _env_file=None,
        )
        assert not settings.is_configured
        assert not settings._has_usable_key_file

    def test_validator_accepts_key_file_only(self, tmp_path: Path) -> None:
        """app_id + key file (no env var) should pass validation."""
        pem = tmp_path / "key.pem"
        pem.write_text("-----BEGIN RSA PRIVATE KEY-----\ndata\n-----END RSA PRIVATE KEY-----")

        settings = GitHubAppSettings(
            app_id="123",
            private_key=SecretStr(""),
            app_private_key_file=str(pem),
            _env_file=None,
        )
        assert settings.is_configured

    def test_validator_rejects_app_id_with_empty_placeholder(self, tmp_path: Path) -> None:
        """app_id + empty placeholder file + no env var = incomplete config."""
        pem = tmp_path / "key.pem"
        pem.touch()  # 0 bytes

        with pytest.raises(ValueError, match="Incomplete GitHub App config"):
            GitHubAppSettings(
                app_id="123",
                private_key=SecretStr(""),
                app_private_key_file=str(pem),
                _env_file=None,
            )

    def test_validator_rejects_app_id_with_nonexistent_file(self) -> None:
        """app_id + nonexistent file path + no env var = incomplete config."""
        with pytest.raises(ValueError, match="Incomplete GitHub App config"):
            GitHubAppSettings(
                app_id="123",
                private_key=SecretStr(""),
                app_private_key_file="/nonexistent/key.pem",
                _env_file=None,
            )

    def test_partial_config_missing_private_key_accepts_key_file(self, tmp_path: Path) -> None:
        """Previously this test required private_key env var; now key file alone is sufficient."""
        pem = tmp_path / "key.pem"
        pem.write_text("-----BEGIN RSA PRIVATE KEY-----\ndata\n-----END RSA PRIVATE KEY-----")

        settings = GitHubAppSettings(
            app_id="123456",
            private_key=SecretStr(""),
            installation_id="123",
            app_private_key_file=str(pem),
            _env_file=None,
        )
        assert settings.is_configured

    def test_key_file_with_no_app_id_raises_error(self, tmp_path: Path) -> None:
        """Key file set but no app_id = incomplete config."""
        pem = tmp_path / "key.pem"
        pem.write_text("-----BEGIN RSA PRIVATE KEY-----\ndata\n-----END RSA PRIVATE KEY-----")

        with pytest.raises(ValueError, match="Incomplete GitHub App config"):
            GitHubAppSettings(
                app_id="",
                private_key=SecretStr(""),
                app_private_key_file=str(pem),
                _env_file=None,
            )
