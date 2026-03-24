"""GitHub App client for secure API access.

This module implements the GitHub App authentication flow:
1. Load private key from settings (base64 encoded)
2. Generate JWT signed with private key (10 min TTL)
3. Exchange JWT for installation token (1 hour TTL)
4. Use installation token for API/git operations

The installation token is short-lived and scoped to only the
repositories where the app is installed.

See Also:
    - https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app
    - docs/deployment/github-app-security.md
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx

from syn_adapters.github.client_api import api_get as _api_get
from syn_adapters.github.client_api import api_post as _api_post
from syn_adapters.github.client_api import api_put as _api_put
from syn_adapters.github.client_api import check_response as _check_response_fn
from syn_adapters.github.client_endpoints import get_app_info as _get_app_info
from syn_adapters.github.client_endpoints import (
    get_installation_for_repo as _get_installation_for_repo,
)
from syn_adapters.github.client_endpoints import get_webhook_config as _get_webhook_config
from syn_adapters.github.client_endpoints import list_accessible_repos as _list_accessible_repos
from syn_adapters.github.client_endpoints import list_installations as _list_installations
from syn_adapters.github.client_endpoints import update_webhook_config as _update_webhook_config
from syn_adapters.github.client_jwt import (
    JWT_ALGORITHM as JWT_ALGORITHM,
)
from syn_adapters.github.client_jwt import (
    decode_private_key,
    generate_jwt,
)
from syn_adapters.github.client_token import get_installation_token as _get_installation_token

if TYPE_CHECKING:
    from syn_shared.settings.github import GitHubAppSettings

logger = logging.getLogger(__name__)

# GitHub API base URL
GITHUB_API_URL = "https://api.github.com"

# Token refresh threshold (refresh when 10 min remaining)
TOKEN_REFRESH_THRESHOLD_SECONDS = 10 * 60


class GitHubAppError(Exception):
    """Base exception for GitHub App errors."""

    pass


class GitHubAuthError(GitHubAppError):
    """Authentication failed."""

    pass


class GitHubRateLimitError(GitHubAppError):
    """Rate limit exceeded."""

    def __init__(self, message: str, reset_at: datetime | None = None) -> None:
        super().__init__(message)
        self.reset_at = reset_at


@dataclass
class InstallationToken:
    """A GitHub installation access token with metadata."""

    token: str
    expires_at: datetime
    permissions: dict[str, str]
    repository_selection: str  # "all" or "selected"

    @property
    def is_expired(self) -> bool:
        """Check if token is expired or about to expire."""
        now = datetime.now(UTC)
        buffer = TOKEN_REFRESH_THRESHOLD_SECONDS
        return (self.expires_at.timestamp() - now.timestamp()) < buffer

    @property
    def seconds_until_expiry(self) -> float:
        """Seconds until token expires."""
        now = datetime.now(UTC)
        return self.expires_at.timestamp() - now.timestamp()


class GitHubAppClient:
    """Secure GitHub App authentication client.

    Generates short-lived installation tokens for git operations.
    Tokens expire in 1 hour (GitHub's limit) and are scoped to
    the specific installation (org/repos).

    Example:
        from syn_adapters.github import get_github_client

        client = get_github_client()

        # Get installation token
        token = await client.get_installation_token()

        # Use for git clone
        url = f"https://x-access-token:{token}@github.com/org/repo.git"

        # Or use for API calls
        response = await client.api_get("/repos/org/repo")
    """

    def __init__(self, settings: GitHubAppSettings) -> None:
        """Initialize the GitHub App client.

        Args:
            settings: GitHub App configuration from environment.

        Raises:
            ValueError: If settings are not fully configured.
        """
        if not settings.is_configured:
            msg = "GitHub App is not fully configured"
            raise ValueError(msg)

        self._settings = settings
        self._private_key: str | None = None
        self._cached_tokens: dict[str, InstallationToken] = {}
        self._http = httpx.AsyncClient(
            base_url=GITHUB_API_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._http.aclose()

    async def __aenter__(self) -> GitHubAppClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    @property
    def app_id(self) -> str:
        """Get the GitHub App ID."""
        assert self._settings.app_id is not None
        return self._settings.app_id

    @property
    def bot_username(self) -> str:
        """Get the bot username for commits."""
        return self._settings.bot_name

    @property
    def bot_email(self) -> str:
        """Get the bot email for commits."""
        return self._settings.bot_email

    def _get_private_key(self) -> str:
        """Get the decoded private key (cached after first decode).

        Returns:
            PEM-formatted private key string.

        Raises:
            GitHubAuthError: If private key is invalid.
        """
        if self._private_key is not None:
            return self._private_key

        try:
            assert self._settings.private_key is not None
            encoded = self._settings.private_key.get_secret_value()
            self._private_key = decode_private_key(encoded)
            return self._private_key
        except Exception as e:
            msg = f"Failed to decode private key: {e}"
            raise GitHubAuthError(msg) from e

    def _generate_jwt(self) -> str:
        """Generate a JWT for GitHub App authentication.

        Returns:
            Signed JWT string (valid for 10 minutes).

        Raises:
            GitHubAuthError: If JWT generation fails.
        """
        try:
            private_key = self._get_private_key()
            return generate_jwt(self.app_id, private_key)
        except Exception as e:
            if isinstance(e, GitHubAuthError):
                raise
            msg = f"Failed to generate JWT: {e}"
            raise GitHubAuthError(msg) from e

    async def get_installation_token(
        self, installation_id: str | None = None, force_refresh: bool = False
    ) -> str:
        """Get a valid installation access token.

        Tokens are cached per installation_id and reused until expired.

        Args:
            installation_id: The installation to get a token for. Use
                get_installation_for_repo() to resolve this from a repo name. Raises if not set.
            force_refresh: If True, always fetch a new token.

        Returns:
            Installation access token string.

        Raises:
            GitHubAuthError: If token generation fails or no installation_id available.
            GitHubRateLimitError: If rate limited.
        """
        return await _get_installation_token(self, installation_id, force_refresh)

    async def api_get(self, path: str, installation_id: str | None = None) -> dict:
        """Make an authenticated GET request to the GitHub API.

        Args:
            path: API path (e.g., "/repos/owner/repo").
            installation_id: Installation to authenticate as. Must be provided explicitly.

        Returns:
            Response JSON as dictionary.

        Raises:
            GitHubAppError: On API errors.
        """
        return await _api_get(self, path, installation_id)

    async def api_post(
        self, path: str, json: dict | None = None, installation_id: str | None = None
    ) -> dict:
        """Make an authenticated POST request to the GitHub API.

        Args:
            path: API path.
            json: Request body.
            installation_id: Installation to authenticate as. Must be provided explicitly.

        Returns:
            Response JSON as dictionary.

        Raises:
            GitHubAppError: On API errors.
        """
        return await _api_post(self, path, json, installation_id)

    async def api_put(
        self, path: str, json: dict | None = None, installation_id: str | None = None
    ) -> dict:
        """Make an authenticated PUT request to the GitHub API.

        Args:
            path: API path.
            json: Request body.
            installation_id: Installation to authenticate as. Must be provided explicitly.

        Returns:
            Response JSON as dictionary.

        Raises:
            GitHubAppError: On API errors.
        """
        return await _api_put(self, path, json, installation_id)

    def _check_response(self, response: httpx.Response) -> None:
        """Check response for errors.

        Raises:
            GitHubRateLimitError: If rate limited.
            GitHubAppError: On other errors.
        """
        _check_response_fn(response)

    async def get_app_info(self) -> dict:
        """Get information about the GitHub App.

        Returns:
            App metadata including name, ID, permissions.
        """
        return await _get_app_info(self)

    async def get_webhook_config(self) -> dict:
        """Get the GitHub App's webhook configuration.

        Uses App-level JWT auth (not installation tokens).

        Returns:
            Webhook config including url, content_type, insecure_ssl, secret.
        """
        return await _get_webhook_config(self)

    async def update_webhook_config(
        self,
        url: str,
        content_type: str = "json",
        insecure_ssl: str = "0",
        secret: str | None = None,
    ) -> dict:
        """Update the GitHub App's webhook configuration.

        Uses App-level JWT auth (not installation tokens).

        Args:
            url: The webhook URL to receive events.
            content_type: Payload content type ('json' or 'form').
            insecure_ssl: '0' to verify SSL, '1' to skip verification.
            secret: Webhook secret for payload signing. If None, keeps existing.

        Returns:
            Updated webhook config.
        """
        return await _update_webhook_config(self, url, content_type, insecure_ssl, secret)

    async def list_installations(self) -> list[dict]:
        """List all installations of this GitHub App.

        Returns:
            List of installation metadata.
        """
        return await _list_installations(self)

    async def list_accessible_repos(self, installation_id: str | None = None) -> list[dict]:
        """List repositories accessible to an installation.

        Args:
            installation_id: The installation to list repos for. Must be provided explicitly.

        Returns:
            List of repository metadata.
        """
        return await _list_accessible_repos(self, installation_id)

    async def get_installation_for_repo(self, repo_full_name: str) -> str:
        """Look up the installation ID for a repository.

        Calls GET /repos/{owner}/{repo}/installation with App JWT auth.
        Requires the GitHub App to be installed on the repo's owner account.

        Args:
            repo_full_name: Repository in "{owner}/{repo}" format.

        Returns:
            Installation ID string.

        Raises:
            GitHubAuthError: If lookup fails or app not installed on repo.
        """
        return await _get_installation_for_repo(self, repo_full_name)


# Singleton instance
_github_client: GitHubAppClient | None = None


def get_github_client() -> GitHubAppClient:
    """Get the singleton GitHub App client.

    Uses settings from environment (SYN_GITHUB_* variables).

    Returns:
        Configured GitHubAppClient instance.

    Raises:
        ValueError: If GitHub App is not configured.
    """
    global _github_client

    if _github_client is not None:
        return _github_client

    from syn_shared.settings import get_settings

    settings = get_settings()

    if not settings.github.is_configured:
        msg = "GitHub App not configured. Set SYN_GITHUB_APP_ID and SYN_GITHUB_PRIVATE_KEY."
        raise ValueError(msg)

    _github_client = GitHubAppClient(settings.github)
    logger.info(
        "GitHub App client initialized (app_id=%s)",
        settings.github.app_id,
    )

    return _github_client


def reset_github_client() -> None:
    """Reset the singleton client (for testing)."""
    global _github_client
    _github_client = None
