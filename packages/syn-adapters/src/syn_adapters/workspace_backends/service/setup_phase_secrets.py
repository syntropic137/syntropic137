"""Setup phase secrets for workspace lifecycle (ADR-024, ADR-058).

This module contains the SetupPhaseSecrets dataclass and related types
for managing secrets during the workspace setup phase.

GitHub authentication is EXCLUSIVELY via GitHub App installation tokens.
No personal access tokens (GH_TOKEN) are supported.

Multi-repo support (ADR-058): one token per unique GitHub App installation,
resolved per-repo via GET /repos/{owner}/{repo}/installation. Repos across
multiple orgs each get their own token; per-repo entries in ~/.git-credentials
ensure git picks the right token for each clone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


def _repo_name(url: str) -> str:
    """Return the repo name from a full GitHub URL.

    Examples:
        "https://github.com/org/repo-a.git" → "repo-a"
        "https://github.com/org/repo-b/"   → "repo-b"
        "https://github.com/org/repo-c"    → "repo-c"
    """
    return url.rstrip("/").split("/")[-1].removesuffix(".git")


def _repo_full_name(url: str) -> str:
    """Return 'owner/repo' from a full GitHub URL.

    Examples:
        "https://github.com/org/repo-a.git" → "org/repo-a"
        "https://github.com/org/repo-b"    → "org/repo-b"
    """
    parts = url.rstrip("/").split("/")
    return f"{parts[-2]}/{parts[-1].removesuffix('.git')}"


def _resolve_claude_credentials() -> tuple[str | None, str | None]:
    """Resolve Claude API credentials from settings."""
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

    return claude_code_oauth_token, anthropic_api_key


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
    """Secrets available only during setup phase (ADR-024, ADR-058).

    These secrets are used to configure credentials during the setup phase,
    then CLEARED before the agent runs. This follows the OpenAI Codex pattern.

    GitHub authentication is EXCLUSIVELY via GitHub App installation tokens.
    No personal access tokens (GH_TOKEN) are supported.

    Multi-repo support (ADR-058): one token per unique GitHub App installation.
    repo_tokens maps each full repo URL to its installation access token.
    Repos from different orgs/accounts resolve to different installations and
    receive different tokens; git credentials are written per-repo to
    ~/.git-credentials so git picks the correct token for each clone.

    Attributes:
        repo_tokens: Full repo URL → installation access token (one per installation)
        repositories: Full repo URLs to clone during setup phase
        claude_code_oauth_token: Claude Code OAuth token (takes priority over API key)
        anthropic_api_key: Claude API key (fallback when OAuth token not set)
        git_author_name: Git commit author name (from GitHub App bot)
        git_author_email: Git commit author email (from GitHub App bot)
    """

    repo_tokens: dict[str, str] = field(default_factory=dict)
    repositories: list[str] = field(default_factory=list)
    claude_code_oauth_token: str | None = None
    anthropic_api_key: str | None = None
    git_author_name: str | None = None
    git_author_email: str | None = None

    @classmethod
    async def create(
        cls,
        *,
        repositories: list[str] | None = None,
        require_github: bool = True,
    ) -> SetupPhaseSecrets:
        """Create SetupPhaseSecrets using GitHub App.

        For each repo URL, resolves its GitHub App installation via
        GET /repos/{owner}/{repo}/installation, groups repos by installation_id,
        and mints one token per unique installation. This supports repos spread
        across multiple orgs or personal accounts.

        Args:
            repositories: Full GitHub URLs to clone. One token is fetched per
                unique GitHub App installation covering these repos.
            require_github: If True (default), raises GitHubAuthError if any
                repo is not covered by a configured GitHub App installation.
                Set False only for workflows with no private GitHub repos.

        Returns:
            SetupPhaseSecrets with repo_tokens and repositories populated.

        Raises:
            GitHubAppNotConfiguredError: If require_github=True and App not configured.
            GitHubAuthError: If require_github=True and any repo returns 404 from
                installation lookup (repo not added to any GitHub App installation).
        """
        repos = repositories or []
        repo_tokens: dict[str, str] = {}
        git_author_name: str | None = None
        git_author_email: str | None = None

        if repos:
            from syn_adapters.github import GitHubAppClient
            from syn_shared.settings.github import GitHubAppSettings

            github_settings = GitHubAppSettings()

            if not github_settings.is_configured:
                if require_github:
                    raise GitHubAppNotConfiguredError()
            else:
                client = GitHubAppClient(github_settings)  # type: ignore[arg-type]

                # Per-repo installation lookup — fail fast on 404 if require_github
                url_to_installation: dict[str, str] = {}
                for url in repos:
                    full_name = _repo_full_name(url)
                    try:
                        installation_id = await client.get_installation_for_repo(full_name)
                        url_to_installation[url] = installation_id
                        logger.debug(
                            "Resolved installation %s for repo %s", installation_id, full_name
                        )
                    except Exception:
                        if require_github:
                            logger.error(
                                "GitHub App not installed on repository: %s. "
                                "Add it at github.com/settings/installations.",
                                full_name,
                            )
                            raise
                        logger.warning(
                            "No GitHub App installation for %s — will attempt clone without token.",
                            full_name,
                        )

                # Group by installation_id → one token per unique installation
                installation_to_urls: dict[str, list[str]] = {}
                for url, inst_id in url_to_installation.items():
                    installation_to_urls.setdefault(inst_id, []).append(url)

                tokens_by_installation: dict[str, str] = {}
                for inst_id in installation_to_urls:
                    token = await client.get_installation_token(inst_id)
                    tokens_by_installation[inst_id] = token
                    logger.info(
                        "Generated token for installation %s (%d repo(s))",
                        inst_id,
                        len(installation_to_urls[inst_id]),
                    )

                for url, inst_id in url_to_installation.items():
                    repo_tokens[url] = tokens_by_installation[inst_id]

                git_author_name = github_settings.bot_name
                git_author_email = github_settings.bot_email

        claude_code_oauth_token, anthropic_api_key = _resolve_claude_credentials()

        return cls(
            repo_tokens=repo_tokens,
            repositories=repos,
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
        repositories: list[str] | None = None,
    ) -> SetupPhaseSecrets:
        """Create SetupPhaseSecrets for testing (no GitHub operations).

        ⚠️  TEST ENVIRONMENT ONLY - no GitHub token is provided.

        Args:
            claude_code_oauth_token: Optional OAuth token for Claude
            anthropic_api_key: Optional API key for Claude
            git_author_name: Git author name (default: "Test Agent")
            git_author_email: Git author email (default: "test@example.com")
            repositories: Optional list of repo URLs (no tokens fetched)
        """
        import os

        from syn_shared.env_constants import ENV_ANTHROPIC_API_KEY, ENV_CLAUDE_CODE_OAUTH_TOKEN

        return cls(
            repo_tokens={},
            repositories=repositories or [],
            claude_code_oauth_token=claude_code_oauth_token
            or os.environ.get(ENV_CLAUDE_CODE_OAUTH_TOKEN),
            anthropic_api_key=anthropic_api_key or os.environ.get(ENV_ANTHROPIC_API_KEY),
            git_author_name=git_author_name,
            git_author_email=git_author_email,
        )

    def build_setup_script(self) -> str:
        """Build the complete bash setup script for this execution.

        When no repositories are configured, returns DEFAULT_SETUP_SCRIPT unchanged
        (backward-compatible with pre-ADR-058 executions).

        When repositories are configured:
        - Writes per-repo credential entries to ~/.git-credentials (not one blanket
          github.com entry) so git picks the correct token for each clone
        - Appends git clone commands with idempotency guards (safe to re-run)
        - Configures gh CLI using the first repo's token for PR/issue operations

        Returns:
            Complete bash script string to run during the setup phase.
        """
        if not self.repositories:
            return DEFAULT_SETUP_SCRIPT

        lines: list[str] = [DEFAULT_SETUP_SCRIPT.rstrip()]

        # Per-repo credentials (not one blanket github.com entry)
        if self.repo_tokens:
            lines.append("")
            lines.append("# Configure per-repo GitHub credentials (ADR-058)")
            lines.append("git config --global credential.helper store")
            for url, token in self.repo_tokens.items():
                full_name = _repo_full_name(url)
                lines.append(
                    f'echo "https://x-access-token:{token}@github.com/{full_name}"'
                    f" >> ~/.git-credentials"
                )
            lines.append("chmod 600 ~/.git-credentials")

            # gh CLI: use first repo's token
            first_token = next(iter(self.repo_tokens.values()))
            lines.append("")
            lines.append("# Configure gh CLI")
            lines.append("mkdir -p ~/.config/gh")
            lines.append("cat > ~/.config/gh/hosts.yml << 'GHEOF'")
            lines.append("github.com:")
            lines.append(f"    oauth_token: {first_token}")
            lines.append('    user: ${GIT_AUTHOR_NAME:-syn-bot}')
            lines.append("    git_protocol: https")
            lines.append("GHEOF")
            lines.append("chmod 600 ~/.config/gh/hosts.yml")

        # Clone repositories with idempotency guard
        lines.append("")
        lines.append("# Clone repositories (ADR-058)")
        lines.append("mkdir -p /workspace/repos")
        for url in self.repositories:
            name = _repo_name(url)
            lines.append(
                f'[ -d "/workspace/repos/{name}" ] || git clone "{url}" "/workspace/repos/{name}"'
            )

        return "\n".join(lines) + "\n"


# Minimal setup script for credentials that require secure injection.
#
# NOTE: Most configuration is now handled by the container's entrypoint.sh
# (see: agentic-primitives/providers/workspaces/claude-cli/scripts/entrypoint.sh)
#
# This script only handles:
# 1. Git identity (in case container started without env vars)
#
# Credential helper and repo cloning are now handled by build_setup_script()
# when repositories are provided (ADR-058). For executions without repos,
# this script is used as-is (backward compat).
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
"""
