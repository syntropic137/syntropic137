"""Development tooling settings with DEV__ prefix.

Environment variables for local development tools use a DEV__ (double underscore)
prefix to clearly distinguish them from application runtime configuration.

Environment Variables:
    DEV__SMEE_URL - Smee.io webhook proxy URL for local development

Usage:
    from aef_shared.settings.dev_tooling import DevToolingSettings

    settings = DevToolingSettings()
    if settings.smee_url:
        # Start smee proxy with this URL
        ...
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DevToolingSettings(BaseSettings):
    """Development tooling settings.

    These are dev-only environment variables that control local tooling
    (webhook proxies, debug servers, etc.). They use the DEV__ prefix
    to clearly separate them from application runtime config.
    """

    model_config = SettingsConfigDict(
        env_prefix="DEV__",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    smee_url: str = Field(
        default="",
        description=(
            "Smee.io webhook proxy URL for local development. "
            "Forwards GitHub webhooks to your local machine. "
            "Create a channel at https://smee.io/new and paste the URL here. "
            "Used by 'just dev' to auto-start the webhook proxy."
        ),
    )
