"""GitHub App settings for secure agent authentication.

This module provides configuration for GitHub App integration.
GitHub Apps provide secure, auto-rotating tokens with fine-grained permissions.

See HANDOFF-GITHUB-APP.md for architecture details.

Environment Variables:
    SYN_GITHUB_* - GitHub App configuration

Usage:
    from syn_shared.settings.github import GitHubAppSettings

    settings = GitHubAppSettings()
    if settings.is_configured:
        client = GitHubAppClient(settings)
        installation_id = await client.get_installation_for_repo("owner/repo")
        token = await client.get_installation_token(installation_id)
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from typing import Self


class GitHubAppSettings(BaseSettings):
    """GitHub App configuration for secure authentication.

    Commits from agents show as `<app_name>[bot]` with full audit trail.
    Installation tokens are auto-rotated (1-hour lifetime).

    Override via SYN_GITHUB_* environment variables.
    """

    model_config = SettingsConfigDict(
        env_prefix="SYN_GITHUB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # =========================================================================
    # APP IDENTITY
    # =========================================================================

    app_id: str = Field(
        default="",
        description=("GitHub App ID. Get from: https://github.com/settings/apps/<app>/general"),
    )

    app_name: str = Field(
        default="syn-app",
        description=(
            "GitHub App name (slug). Used in commit attribution. "
            "Commits will show as '<app_name>[bot]'."
        ),
    )

    # =========================================================================
    # AUTHENTICATION
    # =========================================================================

    private_key: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "GitHub App private key (fallback). Supports three formats: "
            "(1) file:<path> — read PEM from file; "
            "(2) raw PEM starting with '-----BEGIN'; "
            "(3) base64-encoded PEM string. "
            "Prefer SYN_GITHUB_APP_PRIVATE_KEY_FILE for Docker deployments."
        ),
    )

    app_private_key_file: str = Field(
        default="",
        description=(
            "Path to PEM file containing the GitHub App private key. "
            "Takes priority over SYN_GITHUB_PRIVATE_KEY env var. "
            "In Docker: set to /run/secrets/github_app_private_key "
            "(mounted as tmpfs — never hits disk, not visible in docker inspect)."
        ),
    )

    # =========================================================================
    # WEBHOOK SECURITY
    # =========================================================================

    webhook_secret: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "Webhook secret for validating GitHub webhook payloads. "
            "Set when configuring the GitHub App webhook URL. "
            "Used to verify webhook signatures (X-Hub-Signature-256)."
        ),
    )

    # =========================================================================
    # COMPUTED PROPERTIES
    # =========================================================================

    @property
    def is_configured(self) -> bool:
        """Check if GitHub App is configured.

        Returns True if app_id is set AND a private key is available via
        either app_private_key_file (preferred) or private_key env var.
        """
        has_key = bool(self.private_key.get_secret_value())
        has_key_file = bool(self.app_private_key_file) and Path(self.app_private_key_file).is_file()
        return bool(self.app_id and (has_key or has_key_file))

    @property
    def bot_name(self) -> str:
        """Get the bot username for commits.

        Returns:
            Bot username in format '<app_name>[bot]'.
        """
        return f"{self.app_name}[bot]"

    @property
    def bot_email(self) -> str:
        """Get the bot email for commits.

        GitHub uses a special noreply email format for app commits.

        Returns:
            Bot email in format '<app_id>+<app_name>[bot]@users.noreply.github.com'.
        """
        return f"{self.app_id}+{self.app_name}[bot]@users.noreply.github.com"

    # =========================================================================
    # VALIDATION
    # =========================================================================

    @model_validator(mode="after")
    def validate_complete_config(self) -> Self:
        """Ensure GitHub App config is complete or entirely absent.

        app_id requires at least one key source (file or env var).
        A key source without app_id is also a misconfiguration.
        """
        has_app_id = bool(self.app_id)
        has_key = bool(self.private_key.get_secret_value())
        has_key_file = bool(self.app_private_key_file)
        has_any_key = has_key or has_key_file

        if has_app_id and not has_any_key:
            msg = (
                "Incomplete GitHub App config: SYN_GITHUB_APP_ID is set but no private key. "
                "Set SYN_GITHUB_APP_PRIVATE_KEY_FILE or SYN_GITHUB_PRIVATE_KEY."
            )
            raise ValueError(msg)

        if not has_app_id and has_any_key:
            msg = "Incomplete GitHub App config: private key is set but SYN_GITHUB_APP_ID is missing."
            raise ValueError(msg)

        return self


@lru_cache
def get_github_settings() -> GitHubAppSettings:
    """Get cached GitHub App settings.

    Settings are loaded once on first call and cached.

    op:// references in .env or os.environ are transparently resolved via
    the 1Password CLI before pydantic reads them. If `op` is unavailable,
    resolution is silently skipped and pydantic validates as normal.

    Returns:
        Validated GitHubAppSettings instance.
    """
    from syn_shared.settings.op_resolver import resolve_op_secrets

    resolve_op_secrets()
    return GitHubAppSettings()


def reset_github_settings() -> None:
    """Clear GitHub settings cache (for testing)."""
    get_github_settings.cache_clear()
