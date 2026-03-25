"""GitHub App API client.

Handles JWT generation and installation token fetching for GitHub App authentication.
Uses PyJWT for JWT signing and httpx for async HTTP requests.

See: https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app

Usage:
    from syn_shared.settings.github import GitHubAppSettings
    from syn_domain.contexts.github._shared.github_client import GitHubAppClient

    settings = GitHubAppSettings()
    client = GitHubAppClient(settings)
    token_response = await client.get_installation_token(installation_id)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_shared.settings.github import GitHubAppSettings

logger = logging.getLogger(__name__)

# GitHub API base URL
GITHUB_API_URL = "https://api.github.com"


@dataclass
class TokenResponse:
    """Response from GitHub's installation token endpoint.

    Attributes:
        token: The installation access token.
        expires_at: Token expiration time (UTC).
        permissions: Granted permissions.
        repository_selection: 'all' or 'selected'.
    """

    token: str
    expires_at: datetime
    permissions: dict[str, str]
    repository_selection: str


class GitHubAppClientError(Exception):
    """Base exception for GitHub App client errors."""

    pass


class JWTGenerationError(GitHubAppClientError):
    """Failed to generate JWT for GitHub App authentication."""

    pass


class TokenFetchError(GitHubAppClientError):
    """Failed to fetch installation access token."""

    pass


class GitHubAppClient:
    """Client for GitHub App API operations.

    Handles:
    - JWT generation for App authentication
    - Installation token fetching
    - Token caching and refresh

    The client caches installation tokens and refreshes them when needed.
    """

    def __init__(self, settings: GitHubAppSettings) -> None:
        """Initialize the GitHub App client.

        Args:
            settings: GitHub App configuration.

        Raises:
            ValueError: If settings are not configured.
        """
        if not settings.is_configured:
            raise ValueError(
                "GitHub App not configured. Set SYN_GITHUB_APP_ID and SYN_GITHUB_PRIVATE_KEY."
            )

        self._settings = settings
        self._cached_tokens: dict[str, TokenResponse] = {}

    def generate_jwt(self) -> str:
        """Generate a JWT for GitHub App authentication.

        The JWT is used to authenticate as the GitHub App itself (not as an installation).
        It's used to request installation access tokens.

        JWTs are valid for up to 10 minutes. We generate them with a 9-minute expiry
        to ensure they're valid when used.

        Returns:
            A signed JWT string.

        Raises:
            JWTGenerationError: If JWT generation fails.
        """
        try:
            import jwt
        except ImportError as e:
            raise JWTGenerationError(
                "PyJWT package required for GitHub App authentication. "
                "Install with: pip install PyJWT"
            ) from e

        now = int(time.time())

        # JWT payload per GitHub's requirements
        payload = {
            "iat": now - 60,  # Issued 60 seconds ago (clock skew tolerance)
            "exp": now + (9 * 60),  # Expires in 9 minutes
            "iss": self._settings.app_id,  # GitHub App ID
        }

        try:
            private_key = self._settings.private_key.get_secret_value()
            token = jwt.encode(payload, private_key, algorithm="RS256")
            logger.debug(f"Generated JWT for App ID: {self._settings.app_id}")
            return token
        except Exception as e:
            raise JWTGenerationError(f"Failed to generate JWT: {e}") from e

    def _get_cached_token(self, iid: str) -> TokenResponse | None:
        """Return cached token if still valid (with 5-minute buffer), else None."""
        from datetime import timedelta

        cached = self._cached_tokens.get(iid)
        if cached and datetime.now(UTC) + timedelta(minutes=5) < cached.expires_at:
            logger.debug("Using cached installation token for %s", iid)
            return cached
        return None

    async def _fetch_installation_token(self, iid: str) -> TokenResponse:
        """Fetch a fresh installation token from GitHub API."""
        try:
            import httpx
        except ImportError as e:
            raise TokenFetchError(
                "httpx package required for GitHub App authentication. "
                "Install with: pip install httpx"
            ) from e

        jwt_token = self.generate_jwt()
        url = f"{GITHUB_API_URL}/app/installations/{iid}/access_tokens"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {jwt_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as e:
            raise TokenFetchError(
                f"GitHub API error: {e.response.status_code} - {e.response.text}"
            ) from e
        except httpx.RequestError as e:
            raise TokenFetchError(f"Network error fetching token: {e}") from e

        expires_at = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
        token_response = TokenResponse(
            token=data["token"],
            expires_at=expires_at,
            permissions=data.get("permissions", {}),
            repository_selection=data.get("repository_selection", "all"),
        )

        self._cached_tokens[iid] = token_response
        logger.info(f"Fetched new installation token for {iid} (expires: {expires_at.isoformat()})")
        return token_response

    async def get_installation_token(
        self, installation_id: str | None = None, force_refresh: bool = False
    ) -> TokenResponse:
        """Get an installation access token.

        Tokens are cached per installation_id and reused until they expire or
        are about to expire (within 5 minutes).

        Args:
            installation_id: The installation to get a token for. Must be provided explicitly
                (e.g. from a webhook payload or via get_installation_for_repo()).
            force_refresh: Force a new token even if cached token is valid.

        Returns:
            TokenResponse with the access token and metadata.

        Raises:
            TokenFetchError: If token fetch fails or no installation_id available.
        """
        iid = installation_id
        if not iid:
            raise TokenFetchError(
                "No installation_id provided. Pass it explicitly (e.g. from a webhook payload)."
            )

        if not force_refresh:
            cached = self._get_cached_token(iid)
            if cached:
                return cached

        return await self._fetch_installation_token(iid)

    async def get_accessible_repositories(self, installation_id: str | None = None) -> list[dict]:
        """List repositories accessible to an installation.

        Args:
            installation_id: The installation to list repos for. Must be provided explicitly.

        Returns:
            List of repository dictionaries with 'id', 'name', 'full_name', etc.

        Raises:
            TokenFetchError: If API call fails.
        """
        try:
            import httpx
        except ImportError as e:
            raise TokenFetchError("httpx package required") from e

        token = await self.get_installation_token(installation_id)

        url = f"{GITHUB_API_URL}/installation/repositories"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as e:
            raise TokenFetchError(f"Failed to list repositories: {e}") from e

        return data.get("repositories", [])

    async def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """Verify a GitHub webhook signature.

        Args:
            payload: Raw request body bytes.
            signature: X-Hub-Signature-256 header value.

        Returns:
            True if signature is valid.

        Raises:
            ValueError: If webhook secret is not configured.
        """
        import hashlib
        import hmac

        secret = self._settings.webhook_secret.get_secret_value()
        if not secret:
            raise ValueError(
                "Webhook secret not configured: set SYN_GITHUB_WEBHOOK_SECRET environment variable"
            )

        # Compute expected signature
        expected = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

        # Constant-time comparison
        return hmac.compare_digest(expected, signature)


# Singleton client instance
_client: GitHubAppClient | None = None


def get_github_client() -> GitHubAppClient | None:
    """Get the global GitHub App client instance.

    Returns None if GitHub App is not configured.

    Returns:
        GitHubAppClient instance or None.
    """
    global _client

    if _client is not None:
        return _client

    from syn_shared.settings.github import get_github_settings

    settings = get_github_settings()
    if not settings.is_configured:
        return None

    _client = GitHubAppClient(settings)
    return _client


def reset_github_client() -> None:
    """Reset the global GitHub App client (for testing)."""
    global _client
    _client = None
