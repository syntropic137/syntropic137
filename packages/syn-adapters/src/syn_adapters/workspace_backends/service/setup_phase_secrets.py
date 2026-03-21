"""Setup phase secrets for workspace lifecycle (ADR-024).

This module contains the SetupPhaseSecrets dataclass and related types
for managing secrets during the workspace setup phase.

GitHub authentication is EXCLUSIVELY via GitHub App installation tokens.
No personal access tokens (GH_TOKEN) are supported.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class GitHubAppNotConfiguredError(Exception):
    """Raised when GitHub App is required but not configured."""

    def __init__(self) -> None:
        super().__init__(
            "GitHub App is not configured. Set GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY, "
            "and GITHUB_APP_INSTALLATION_ID environment variables. "
            "See docs/deployment/github-app-setup.md for details."
        )


@dataclass
class SetupPhaseSecrets:
    """Secrets available only during setup phase (ADR-024).

    These secrets are used to configure credentials during the setup phase,
    then CLEARED before the agent runs. This follows the OpenAI Codex pattern.

    GitHub authentication is EXCLUSIVELY via GitHub App installation tokens.
    No personal access tokens (GH_TOKEN) are supported - this reduces cognitive
    load and ensures consistent, auditable authentication.

    Attributes:
        github_app_token: GitHub App installation token (short-lived, scoped)
        claude_code_oauth_token: Claude Code OAuth token (takes priority over API key)
        anthropic_api_key: Claude API key (fallback when OAuth token not set)
        git_author_name: Git commit author name (from GitHub App bot)
        git_author_email: Git commit author email (from GitHub App bot)

    Usage:
        # Create with GitHub App token (required)
        secrets = await SetupPhaseSecrets.create()

        # For testing only (no GitHub operations)
        secrets = SetupPhaseSecrets.for_testing(anthropic_api_key="sk-ant-xxx")
    """

    github_app_token: str | None = None
    claude_code_oauth_token: str | None = None
    anthropic_api_key: str | None = None
    git_author_name: str | None = None
    git_author_email: str | None = None

    @classmethod
    async def create(
        cls,
        *,
        repository: str | None = None,
        require_github: bool = True,
    ) -> SetupPhaseSecrets:
        """Create SetupPhaseSecrets using GitHub App.

        This is the production factory method. It:
        1. Uses GitHub App to generate a short-lived installation token
        2. Uses GitHub App bot identity for git commits
        3. Reads ANTHROPIC_API_KEY from environment

        Args:
            repository: Repository in "{owner}/{repo}" format. Required to resolve
                the correct GitHub App installation ID for the repo.
            require_github: If True (default), raises if GitHub App not configured

        Returns:
            SetupPhaseSecrets with credentials

        Raises:
            GitHubAppNotConfiguredError: If require_github=True and App not configured
        """
        from syn_adapters.github.client import GitHubAuthError
        from syn_shared.settings.github import GitHubAppSettings

        github_app_token = None
        git_author_name = None
        git_author_email = None

        # GitHub App is the ONLY supported method for GitHub auth
        github_settings = GitHubAppSettings()
        if github_settings.is_configured:
            try:
                from syn_adapters.github import GitHubAppClient

                client = GitHubAppClient(github_settings)
                if repository:
                    installation_id = await client.get_installation_for_repo(repository)
                elif require_github:
                    msg = (
                        "Cannot generate GitHub App token: no repository provided. "
                        "Pass repository='{owner}/{repo}' to SetupPhaseSecrets.create()."
                    )
                    raise GitHubAuthError(msg)
                else:
                    installation_id = None
                if installation_id:
                    github_app_token = await client.get_installation_token(installation_id)
                # Use GitHub App bot identity for commits
                git_author_name = github_settings.bot_name
                git_author_email = github_settings.bot_email
                logger.info(
                    "Generated GitHub App installation token (bot: %s)",
                    github_settings.bot_name,
                )
            except Exception as e:
                logger.error("Failed to get GitHub App token: %s", e)
                if require_github:
                    raise
        elif require_github:
            raise GitHubAppNotConfiguredError()

        # Get Claude auth from Settings (validated by pydantic-settings at startup)
        # CLAUDE_CODE_OAUTH_TOKEN takes priority over ANTHROPIC_API_KEY
        from syn_shared.settings import get_settings

        settings = get_settings()
        claude_code_oauth_token = (
            settings.claude_code_oauth_token.get_secret_value()
            if settings.claude_code_oauth_token
            else None
        )
        anthropic_api_key = (
            settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        )

        if claude_code_oauth_token and anthropic_api_key:
            logger.warning(
                "Both CLAUDE_CODE_OAUTH_TOKEN and ANTHROPIC_API_KEY are set. "
                "Using CLAUDE_CODE_OAUTH_TOKEN."
            )

        return cls(
            github_app_token=github_app_token,
            claude_code_oauth_token=claude_code_oauth_token,
            anthropic_api_key=anthropic_api_key,
            git_author_name=git_author_name,
            git_author_email=git_author_email,
        )

    @classmethod
    def for_testing(
        cls,
        *,
        claude_code_oauth_token: str | None = None,
        anthropic_api_key: str | None = None,
        git_author_name: str = "Test Agent",
        git_author_email: str = "test@example.com",
    ) -> SetupPhaseSecrets:
        """Create SetupPhaseSecrets for testing (no GitHub operations).

        ⚠️  TEST ENVIRONMENT ONLY - no GitHub token is provided.

        Args:
            claude_code_oauth_token: Optional OAuth token for Claude
            anthropic_api_key: Optional API key for Claude
            git_author_name: Git author name (default: "Test Agent")
            git_author_email: Git author email (default: "test@example.com")

        Returns:
            SetupPhaseSecrets without GitHub token
        """
        import os

        from syn_shared.env_constants import ENV_ANTHROPIC_API_KEY, ENV_CLAUDE_CODE_OAUTH_TOKEN

        return cls(
            github_app_token=None,
            claude_code_oauth_token=claude_code_oauth_token
            or os.environ.get(ENV_CLAUDE_CODE_OAUTH_TOKEN),
            anthropic_api_key=anthropic_api_key or os.environ.get(ENV_ANTHROPIC_API_KEY),
            git_author_name=git_author_name,
            git_author_email=git_author_email,
        )


# Minimal setup script for credentials that require secure injection.
#
# NOTE: Most configuration is now handled by the container's entrypoint.sh
# (see: agentic-primitives/providers/workspaces/claude-cli/scripts/entrypoint.sh)
#
# This script only handles:
# 1. Git credentials with GITHUB_APP_TOKEN (passed securely during setup phase)
# 2. Git identity (in case container started without env vars)
#
# The entrypoint already handles: ~/.claude/settings.json, workspace dirs, hooks
DEFAULT_SETUP_SCRIPT = """#!/bin/bash
set -e

# Configure Git identity if not already set by entrypoint
# (entrypoint sets from initial env vars, this ensures setup-phase vars are used)
if [ -n "${GIT_AUTHOR_NAME}" ]; then
    git config --global user.name "${GIT_AUTHOR_NAME}"
    git config --global user.email "${GIT_AUTHOR_EMAIL:-agent@agentic.local}"
fi

# Configure Git credential helper with GitHub App token
# This is the ONLY secure way to inject GitHub credentials - via setup phase
# The token is passed as env var, stored in credentials file, then env is cleared
if [ -n "${GITHUB_APP_TOKEN}" ]; then
    git config --global credential.helper store
    echo "https://x-access-token:${GITHUB_APP_TOKEN}@github.com" > ~/.git-credentials
    chmod 600 ~/.git-credentials

    # Configure gh CLI
    mkdir -p ~/.config/gh
    cat > ~/.config/gh/hosts.yml << EOF
github.com:
    oauth_token: ${GITHUB_APP_TOKEN}
    user: ${GIT_AUTHOR_NAME:-syn-bot}
    git_protocol: https
EOF
    chmod 600 ~/.config/gh/hosts.yml
    echo "GitHub credentials configured"
fi
"""
