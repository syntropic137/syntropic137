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

import shlex

import logging
from dataclasses import dataclass, field
from typing import Protocol

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


def _resolve_codex_credentials() -> str | None:
    """Resolve the Codex auth file contents from settings."""
    from syn_shared.settings import get_settings

    codex_auth_json = get_settings().codex_auth_json
    return codex_auth_json.get_secret_value() if codex_auth_json else None


class GitHubAppNotConfiguredError(Exception):
    """Raised when GitHub App is required but not configured."""

    def __init__(self) -> None:
        super().__init__(
            "GitHub App is not configured. Set GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY, "
            "and GITHUB_APP_INSTALLATION_ID environment variables. "
            "See docs/deployment/github-app-setup.md for details."
        )


class _GitHubClientProtocol(Protocol):
    """Structural protocol for GitHubAppClient — avoids circular import."""

    async def get_installation_for_repo(self, full_name: str) -> str: ...
    async def get_installation_token(self, installation_id: str) -> str: ...


async def _resolve_github_auth(
    repos: list[str],
    require_github: bool,
) -> tuple[dict[str, str], str | None, str | None]:
    """Resolve GitHub App tokens for all repos and return (repo_tokens, author_name, author_email).

    Imports GitHubAppClient and GitHubAppSettings lazily to avoid loading GitHub
    auth machinery for executions that don't need it.
    """
    from syn_adapters.github import GitHubAppClient
    from syn_shared.settings.github import GitHubAppSettings

    github_settings = GitHubAppSettings()

    if not github_settings.is_configured:
        if require_github:
            raise GitHubAppNotConfiguredError()
        return {}, None, None

    client: _GitHubClientProtocol = GitHubAppClient(github_settings)  # type: ignore[arg-type]
    url_to_installation = await _lookup_installations(client, repos, require_github)
    repo_tokens = await _mint_tokens_per_installation(client, url_to_installation)
    return repo_tokens, github_settings.bot_name, github_settings.bot_email


async def _lookup_installations(
    client: _GitHubClientProtocol,
    repos: list[str],
    require_github: bool,
) -> dict[str, str]:
    """Map each repo URL to its GitHub App installation_id.

    Fails fast (re-raises) on any lookup error when require_github=True.
    Silently skips repos with no installation when require_github=False.
    """
    url_to_installation: dict[str, str] = {}
    for url in repos:
        full_name = _repo_full_name(url)
        try:
            installation_id = await client.get_installation_for_repo(full_name)
            url_to_installation[url] = installation_id
            logger.debug("Resolved installation %s for repo %s", installation_id, full_name)
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
    return url_to_installation


async def _mint_tokens_per_installation(
    client: _GitHubClientProtocol,
    url_to_installation: dict[str, str],
) -> dict[str, str]:
    """Mint one token per unique installation and return url → token mapping."""
    installation_to_urls: dict[str, list[str]] = {}
    for url, inst_id in url_to_installation.items():
        installation_to_urls.setdefault(inst_id, []).append(url)

    tokens_by_installation: dict[str, str] = {}
    for inst_id, urls in installation_to_urls.items():
        token = await client.get_installation_token(inst_id)
        tokens_by_installation[inst_id] = token
        logger.info("Generated token for installation %s (%d repo(s))", inst_id, len(urls))

    return {url: tokens_by_installation[inst_id] for url, inst_id in url_to_installation.items()}


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
        codex_auth_json: Full contents of the Codex auth.json file
        git_author_name: Git commit author name (from GitHub App bot)
        git_author_email: Git commit author email (from GitHub App bot)
    """

    repo_tokens: dict[str, str] = field(default_factory=dict)
    repositories: list[str] = field(default_factory=list)
    claude_code_oauth_token: str | None = None
    anthropic_api_key: str | None = None
    codex_auth_json: str | None = None
    git_author_name: str | None = None
    git_author_email: str | None = None

    @classmethod
    async def create(
        cls,
        *,
        repositories: list[str] | None = None,
        require_github: bool = True,
        include_codex_auth: bool = False,
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
            repo_tokens, git_author_name, git_author_email = await _resolve_github_auth(
                repos, require_github
            )

        claude_code_oauth_token, anthropic_api_key = _resolve_claude_credentials()
        # Scope the codex credential to codex phases only: a claude phase's agent
        # must never be able to read the OpenAI auth file (and vice-versa).
        codex_auth_json = _resolve_codex_credentials() if include_codex_auth else None

        return cls(
            repo_tokens=repo_tokens,
            repositories=repos,
            claude_code_oauth_token=claude_code_oauth_token,
            anthropic_api_key=anthropic_api_key,
            codex_auth_json=codex_auth_json,
            git_author_name=git_author_name,
            git_author_email=git_author_email,
        )

    @classmethod
    def for_testing(
        cls,
        *,
        claude_code_oauth_token: str | None = None,
        anthropic_api_key: str | None = None,
        codex_auth_json: str | None = None,
        git_author_name: str = "Test Agent",
        git_author_email: str = "test@example.com",
        repositories: list[str] | None = None,
        repo_tokens: dict[str, str] | None = None,
    ) -> SetupPhaseSecrets:
        """Create SetupPhaseSecrets for testing (no GitHub operations).

        ⚠️  TEST ENVIRONMENT ONLY - no GitHub token is provided.

        Args:
            claude_code_oauth_token: Optional OAuth token for Claude
            anthropic_api_key: Optional API key for Claude
            codex_auth_json: Optional full contents of Codex auth.json
            git_author_name: Git author name (default: "Test Agent")
            git_author_email: Git author email (default: "test@example.com")
            repositories: Optional list of repo URLs (no tokens fetched)
            repo_tokens: Optional pre-minted URL→token map for tests that need credentials
        """
        import os

        from syn_shared.env_constants import (
            ENV_ANTHROPIC_API_KEY,
            ENV_CLAUDE_CODE_OAUTH_TOKEN,
            ENV_CODEX_AUTH_JSON,
        )

        return cls(
            repo_tokens=repo_tokens or {},
            repositories=repositories or [],
            claude_code_oauth_token=claude_code_oauth_token
            or os.environ.get(ENV_CLAUDE_CODE_OAUTH_TOKEN),
            anthropic_api_key=anthropic_api_key or os.environ.get(ENV_ANTHROPIC_API_KEY),
            codex_auth_json=codex_auth_json or os.environ.get(ENV_CODEX_AUTH_JSON),
            git_author_name=git_author_name,
            git_author_email=git_author_email,
        )

    def build_setup_script(self) -> str:
        """Build the complete bash setup script for this execution.

        Codex authentication setup is included independently of repositories.
        When repositories are configured, the script also:
        - Writes per-repo credential entries to ~/.git-credentials (not one blanket
          github.com entry) so git picks the correct token for each clone
        - Appends git clone commands with idempotency guards (safe to re-run)
        - Configures gh CLI using the first repo's token for PR/issue operations

        Returns:
            Complete bash script string to run during the setup phase.
        """
        lines: list[str] = [DEFAULT_SETUP_SCRIPT.rstrip()]
        self._append_codex_auth(lines)

        if self.repositories:
            self._append_git_credentials(lines)
            self._append_repo_clones(lines)

        return "\n".join(lines) + "\n"

    def _append_codex_auth(self, lines: list[str]) -> None:
        """Relocate the staged codex auth file to ~/.codex/auth.json (0600).

        The auth contents are injected separately as
        ``/workspace/.setup/codex-auth.json`` (never embedded in this script),
        because the docker copy path always writes under /workspace. This moves
        it to ~/.codex/auth.json with mode 0600 and removes the staged copy so
        no credential remains readable under /workspace.
        """
        if not self.codex_auth_json:
            return

        lines.extend(
            [
                "",
                "# Relocate the codex auth file staged under .setup during injection",
                "mkdir -p -m 700 ~/.codex",
                "install -m 600 /workspace/.setup/codex-auth.json ~/.codex/auth.json",
                "rm -f /workspace/.setup/codex-auth.json",
            ]
        )

    def _append_git_credentials(self, lines: list[str]) -> None:
        """Append per-repository GitHub credential configuration."""
        if self.repo_tokens:
            lines.append("")
            lines.append("# Configure per-repo GitHub credentials (ADR-058)")
            lines.append("git config --global credential.helper store")
            # Without useHttpPath, git-credential-store ignores the path component and
            # matches on host alone, so the FIRST github.com entry is handed out for
            # every github.com request -- including a .gitmodules URL pointing at a
            # different private repo the installation happens to cover. Verified against
            # git 2.50.1: an unlisted repo receives the first stored token. Scoping by
            # path makes an unlisted repo receive nothing instead. (#953)
            lines.append("git config --global credential.https://github.com.useHttpPath true")
            for url, token in self.repo_tokens.items():
                full_name = _repo_full_name(url)
                # Path matching is exact, and submodule URLs commonly carry a .git
                # suffix while canonical clone URLs do not. Store both spellings.
                for path in (full_name, f"{full_name}.git"):
                    credential = f"https://x-access-token:{token}@github.com/{path}"
                    lines.append(f"printf '%s\\n' {shlex.quote(credential)} >> ~/.git-credentials")
            lines.append("chmod 600 ~/.git-credentials")

            # gh CLI: use first repo's token
            first_token = next(iter(self.repo_tokens.values()))
            lines.append("")
            lines.append("# Configure gh CLI")
            lines.append("mkdir -p ~/.config/gh")
            lines.append("cat > ~/.config/gh/hosts.yml << 'GHEOF'")
            lines.append("github.com:")
            lines.append(f"    oauth_token: {first_token}")
            lines.append("    user: ${GIT_AUTHOR_NAME:-syn-bot}")
            lines.append("    git_protocol: https")
            lines.append("GHEOF")
            lines.append("chmod 600 ~/.config/gh/hosts.yml")

    def _append_repo_clones(self, lines: list[str]) -> None:
        """Append repository clone commands with idempotency guards.

        Submodules are initialized in a separate step rather than via
        ``git clone --recurse-submodules``. A submodule URL points wherever the
        repo author put it, which is frequently a repo the installation token
        does not cover, and the setup script runs under ``set -e`` -- folding
        the two together would turn one unreachable submodule into a total
        clone failure for the whole execution. Keeping it separate and
        tolerant means a repo with an unreachable submodule still lands, and
        the reason is visible in the setup log.
        """
        lines.append("")
        lines.append("# Clone repositories (ADR-058)")
        lines.append("mkdir -p /workspace/repos")
        for url in self.repositories:
            name = _repo_name(url)
            dest = f"/workspace/repos/{name}"
            lines.append(
                f"[ -d {shlex.quote(dest)} ] || git clone {shlex.quote(url)} {shlex.quote(dest)}"
            )
            # Outside the guard above: a repo cloned by an earlier setup phase may
            # still have uninitialized submodules. `submodule update --init` is
            # idempotent, so re-running it on a complete checkout is a no-op.
            #
            # GIT_ALLOW_PROTOCOL pins the transport allowlist for this command instead
            # of inheriting it. Current git already defaults ext=never (since 2.12) and
            # file=user (since the Oct 2022 security releases), but those are defaults
            # a global config or a future image can move; .gitmodules is controlled by
            # the cloned repo, so the allowlist is stated rather than assumed.
            warning = (
                f"WARNING: submodule init failed for {name}"
                " (unreachable, unauthorized, or disallowed transport);"
                " continuing with a partial checkout"
            )
            lines.append(
                f"GIT_ALLOW_PROTOCOL=https git -C {shlex.quote(dest)}"
                " submodule update --init --recursive"
                f" || printf '%s\\n' {shlex.quote(warning)} >&2"
            )


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
