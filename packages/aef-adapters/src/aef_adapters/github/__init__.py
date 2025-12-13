"""GitHub App integration for secure repository access.

This module provides secure GitHub API access using GitHub Apps
instead of Personal Access Tokens. Tokens are short-lived (1 hour)
and scoped to specific installations.

Usage:
    from aef_adapters.github import GitHubAppClient, get_github_client

    # Get singleton client (uses settings from environment)
    client = get_github_client()

    # Get installation token (1 hour TTL)
    token = await client.get_installation_token()

    # Use for git operations
    git clone https://x-access-token:{token}@github.com/org/repo.git

See Also:
    - docs/deployment/github-app-security.md
    - docs/adrs/ADR-022-secure-token-architecture.md
"""

from aef_adapters.github.client import (
    GitHubAppClient,
    GitHubAppError,
    GitHubAuthError,
    GitHubRateLimitError,
    get_github_client,
    reset_github_client,
)

__all__ = [
    "GitHubAppClient",
    "GitHubAppError",
    "GitHubAuthError",
    "GitHubRateLimitError",
    "get_github_client",
    "reset_github_client",
]
