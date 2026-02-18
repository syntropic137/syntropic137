"""Shared components for the GitHub context.

Contains:
- Value objects: InstallationId, InstallationToken
- GitHub API client
"""

from syn_domain.contexts.github._shared.github_client import (
    GitHubAppClient,
    GitHubAppClientError,
    JWTGenerationError,
    TokenFetchError,
    TokenResponse,
    get_github_client,
    reset_github_client,
)
from syn_domain.contexts.github._shared.value_objects import (
    GitHubAccount,
    InstallationId,
    InstallationToken,
    RepositoryPermission,
)

__all__ = [
    "GitHubAccount",
    "GitHubAppClient",
    "GitHubAppClientError",
    "InstallationId",
    "InstallationToken",
    "JWTGenerationError",
    "RepositoryPermission",
    "TokenFetchError",
    "TokenResponse",
    "get_github_client",
    "reset_github_client",
]
