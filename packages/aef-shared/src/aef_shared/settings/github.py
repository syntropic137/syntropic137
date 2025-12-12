"""GitHub App settings for secure API authentication.

Provides configuration for GitHub App authentication which enables:
- Short-lived, auto-rotating installation tokens
- Granular repository permissions
- Webhook signature verification
- Proper commit attribution (bot identity)

See docs/deployment/github-app-setup.md for setup instructions.

Environment Variables:
    AEF_GITHUB_APP_ID - GitHub App ID (from app settings page)
    AEF_GITHUB_APP_NAME - App slug (e.g., 'aef-engineer-beta')
    AEF_GITHUB_INSTALLATION_ID - Installation ID per organization
    AEF_GITHUB_PRIVATE_KEY - PEM private key for JWT signing
    AEF_GITHUB_WEBHOOK_SECRET - HMAC secret for webhook verification
"""

from __future__ import annotations

from typing import Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class GitHubAppSettings(BaseSettings):
    """GitHub App authentication settings.

    Used for secure GitHub API access with installation tokens.
    All fields are optional to support development without GitHub integration.

    For production, all fields should be configured.
    See: https://docs.github.com/en/apps/creating-github-apps

    Attributes:
        app_id: Numeric App ID from GitHub App settings.
        app_name: App slug used for commit attribution.
        installation_id: Installation ID for the target organization.
        private_key: RSA private key in PEM format for JWT signing.
        webhook_secret: HMAC secret for verifying webhook payloads.
    """

    model_config = SettingsConfigDict(
        env_prefix="AEF_GITHUB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # =========================================================================
    # APP IDENTITY
    # =========================================================================

    app_id: str | None = Field(
        default=None,
        description=(
            "GitHub App ID (numeric). "
            "Find at: https://github.com/settings/apps/<app-name> → General → App ID"
        ),
    )

    app_name: str | None = Field(
        default=None,
        description=(
            "GitHub App slug/name for commit attribution. "
            "Example: 'aef-engineer-beta' → commits appear as 'aef-engineer-beta[bot]'"
        ),
    )

    # =========================================================================
    # INSTALLATION
    # =========================================================================

    installation_id: str | None = Field(
        default=None,
        description=(
            "Installation ID for the organization/account. "
            "Find at: https://github.com/settings/installations → Configure → URL contains ID. "
            "Note: Each org/account has a unique installation ID."
        ),
    )

    # =========================================================================
    # AUTHENTICATION
    # =========================================================================

    private_key: SecretStr | None = Field(
        default=None,
        description=(
            "RSA private key in PEM format for JWT signing. "
            "Generate at: https://github.com/settings/apps/<app-name> → Private keys. "
            "Can be raw PEM or base64-encoded. Multi-line values supported in .env with quotes."
        ),
    )

    webhook_secret: SecretStr | None = Field(
        default=None,
        description=(
            "HMAC secret for webhook signature verification (X-Hub-Signature-256). "
            "Set during GitHub App creation. Use a strong random value. "
            "Generate with: openssl rand -hex 32"
        ),
    )

    # =========================================================================
    # COMPUTED PROPERTIES
    # =========================================================================

    @property
    def is_configured(self) -> bool:
        """Check if GitHub App is fully configured for API access.

        Returns:
            True if app_id, installation_id, and private_key are all set.
        """
        return bool(self.app_id and self.installation_id and self.private_key)

    @property
    def can_verify_webhooks(self) -> bool:
        """Check if webhook verification is enabled.

        Returns:
            True if webhook_secret is configured.
        """
        return self.webhook_secret is not None

    @property
    def bot_username(self) -> str | None:
        """Get the bot username for commit attribution.

        Returns:
            Bot username in format 'app-name[bot]' or None if not configured.
        """
        if self.app_name:
            return f"{self.app_name}[bot]"
        return None

    @property
    def bot_email(self) -> str | None:
        """Get the bot email for commit attribution.

        GitHub uses a special noreply format for bot commits.

        Returns:
            Bot email in format 'APP_ID+app-name[bot]@users.noreply.github.com'
            or None if not configured.
        """
        if self.app_id and self.app_name:
            return f"{self.app_id}+{self.app_name}[bot]@users.noreply.github.com"
        return None

    # =========================================================================
    # VALIDATION
    # =========================================================================

    @model_validator(mode="after")
    def validate_partial_config(self) -> Self:
        """Warn if GitHub App is partially configured.

        Raises ValueError if some but not all required fields are set,
        as this likely indicates a configuration error.
        """
        required_fields = [self.app_id, self.installation_id, self.private_key]
        provided = sum(1 for f in required_fields if f is not None)

        # All or nothing - partial config is likely an error
        if 0 < provided < 3:
            missing = []
            if not self.app_id:
                missing.append("AEF_GITHUB_APP_ID")
            if not self.installation_id:
                missing.append("AEF_GITHUB_INSTALLATION_ID")
            if not self.private_key:
                missing.append("AEF_GITHUB_PRIVATE_KEY")
            msg = (
                f"Incomplete GitHub App configuration. "
                f"Missing: {', '.join(missing)}. "
                f"Either configure all required fields or none."
            )
            raise ValueError(msg)

        return self
