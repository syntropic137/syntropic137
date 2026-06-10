"""Development tooling settings with DEV__ prefix.

Environment variables for local development tools use a DEV__ (double underscore)
prefix to clearly distinguish them from application runtime configuration.

See ADR-004: Environment Configuration with Pydantic Settings.

Environment Variables:
    DEV__API_URL  - API URL for dev tools (seed scripts, replay, E2E tests)
    DEV__SMEE_URL - Smee.io webhook proxy URL for local development

Usage:
    from syn_shared.settings.dev_tooling import get_dev_api_url

    api_url = get_dev_api_url()
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from syn_shared.settings.constants import DEFAULT_DEV_API_URL


class DevToolingSettings(BaseSettings):
    """Development tooling settings.

    These are dev-only environment variables that control local tooling
    (webhook proxies, debug servers, etc.). They use the DEV__ prefix
    to clearly separate them from application runtime config.

    See ADR-004: Environment Configuration with Pydantic Settings.
    """

    model_config = SettingsConfigDict(
        env_prefix="DEV__",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    api_url: str = Field(
        default=DEFAULT_DEV_API_URL,
        description=(
            "API URL for dev tools (seed scripts, replay scripts, E2E tests). "
            "Dev stack exposes the API directly on port 9137. "
            "Selfhost users access the API via the gateway (SYN_GATEWAY_PORT, default 8137). "
            "See ADR-004."
        ),
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

    workflow_fail_on_plugin_not_registered: bool = Field(
        default=True,
        description=(
            "When seeding workflows from disk (issue #726, Phase A), fail boot "
            "if a claude_plugins ref is not in the lock projection. Set to "
            "false in dev/CI to log the error and skip the failing workflow "
            "while still seeding the rest. Production should leave this true "
            "so an unregistered plugin ref never silently lands a half-"
            "installed workflow set. Plugins must be registered via "
            "POST /claude-plugins/registrations before seeding."
        ),
    )


def get_dev_api_url() -> str:
    """Resolve API URL for dev tools.

    Precedence: DEV__API_URL env var > DevToolingSettings default (localhost:9137).
    See ADR-004: Environment Configuration with Pydantic Settings.
    """
    settings = DevToolingSettings()
    return settings.api_url
