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
            "GitHub App private key, base64-encoded. "
            "Download the .pem from: https://github.com/settings/apps/<app>/privatekeys "
            "Encode it: cat your-app.pem | base64 | tr -d '\\n' | pbcopy "
            "Paste the result as the value. Never commit the raw key to git!"
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

        Returns True if the App identity fields are set:
        - app_id
        - private_key (non-empty)

        Note: Installations are resolved dynamically per-repo via
        get_installation_for_repo(), since a single app can be installed
        on multiple orgs/accounts.
        """
        return bool(self.app_id and self.private_key.get_secret_value())

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
        """Ensure GitHub App identity fields are both set or both absent.

        app_id and private_key must be provided together — one without
        the other is a misconfiguration.

        Installations are resolved dynamically per-repo for multi-tenant support.
        """
        identity_fields = [
            self.app_id,
            self.private_key.get_secret_value(),
        ]
        provided = sum(1 for f in identity_fields if f)

        if provided == 1:
            missing = []
            if not self.app_id:
                missing.append("SYN_GITHUB_APP_ID")
            if not self.private_key.get_secret_value():
                missing.append("SYN_GITHUB_PRIVATE_KEY")
            msg = f"Incomplete GitHub App config. Missing: {', '.join(missing)}"
            raise ValueError(msg)

        return self


@lru_cache
def get_github_settings() -> GitHubAppSettings:
    """Get cached GitHub App settings.

    Settings are loaded once on first call and cached.

    Returns:
        Validated GitHubAppSettings instance.
    """
    return GitHubAppSettings()


def reset_github_settings() -> None:
    """Clear GitHub settings cache (for testing)."""
    get_github_settings.cache_clear()
