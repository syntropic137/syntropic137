"""Credential validation — exports API keys and validates GitHub App config."""

from __future__ import annotations

import logging
import os

from syn_api._wiring import get_github_settings
from syn_shared.env_constants import ENV_ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)


def validate_credentials(degraded_reasons: list[str]) -> None:
    """Validate API keys and GitHub App configuration (degraded, not critical).

    Exports ANTHROPIC_API_KEY to os.environ for agent adapters.
    Missing credentials add to degraded_reasons but never abort startup.

    Args:
        degraded_reasons: Mutable list — appended to when credentials are missing.
    """
    from syn_shared.settings import get_settings

    settings = get_settings()

    # Export Anthropic API key if available (needed for agent execution, not dashboard)
    api_key = settings.anthropic_api_key
    api_key_value = api_key.get_secret_value() if api_key else ""
    oauth_value = settings.claude_code_oauth_token.get_secret_value() if settings.claude_code_oauth_token else ""
    if api_key_value:
        os.environ[ENV_ANTHROPIC_API_KEY] = api_key_value
    elif oauth_value:
        logger.info("Using CLAUDE_CODE_OAUTH_TOKEN for agent execution (no ANTHROPIC_API_KEY)")
    elif not settings.is_test:
        logger.warning(
            "ANTHROPIC_API_KEY not configured — agent execution disabled. "
            "Set it in .env or 1Password to enable workflow runs."
        )
        degraded_reasons.append("anthropic_api_key")

    # Validate GitHub App (warn-only — dashboard should work without it)
    try:
        github = get_github_settings()
        if not github.is_configured and not settings.is_test:
            logger.warning(
                "GitHub App not configured — webhook triggers disabled. "
                "Run 'just onboard --stage configure_github_app' to configure."
            )
            degraded_reasons.append("github_app")
    except Exception:
        logger.exception("Failed to validate GitHub App configuration")
        degraded_reasons.append("github_app")
