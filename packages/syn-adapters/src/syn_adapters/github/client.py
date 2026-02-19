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

import base64
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
import jwt

if TYPE_CHECKING:
    from syn_shared.settings.github import GitHubAppSettings

logger = logging.getLogger(__name__)

# GitHub API base URL
GITHUB_API_URL = "https://api.github.com"

# JWT algorithm for GitHub App authentication
JWT_ALGORITHM = "RS256"

# JWT validity period (GitHub allows max 10 minutes)
JWT_EXPIRY_SECONDS = 10 * 60

# Clock skew buffer (issue JWT 60 seconds in the past)
CLOCK_SKEW_SECONDS = 60

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
        """Get the decoded private key.

        The private key is stored base64-encoded in settings.
        This method decodes it on first access and caches the result.

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
            self._private_key = base64.b64decode(encoded).decode("utf-8")
            return self._private_key
        except Exception as e:
            msg = f"Failed to decode private key: {e}"
            raise GitHubAuthError(msg) from e

    def _generate_jwt(self) -> str:
        """Generate a JWT for GitHub App authentication.

        The JWT is signed with the private key and used to
        request installation access tokens.

        Returns:
            Signed JWT string (valid for 10 minutes).

        Raises:
            GitHubAuthError: If JWT generation fails.
        """
        now = int(time.time())

        payload = {
            # Issued at (with clock skew buffer)
            "iat": now - CLOCK_SKEW_SECONDS,
            # Expires in 10 minutes
            "exp": now + JWT_EXPIRY_SECONDS,
            # Issuer is the App ID
            "iss": self.app_id,
        }

        try:
            private_key = self._get_private_key()
            return jwt.encode(payload, private_key, algorithm=JWT_ALGORITHM)
        except jwt.PyJWTError as e:
            msg = f"Failed to generate JWT: {e}"
            raise GitHubAuthError(msg) from e

    async def get_installation_token(
        self, installation_id: str | None = None, force_refresh: bool = False
    ) -> str:
        """Get a valid installation access token.

        Tokens are cached per installation_id and reused until expired.

        Args:
            installation_id: The installation to get a token for. Falls back to
                SYN_GITHUB_INSTALLATION_ID if not provided. Raises if neither is set.
            force_refresh: If True, always fetch a new token.

        Returns:
            Installation access token string.

        Raises:
            GitHubAuthError: If token generation fails or no installation_id available.
            GitHubRateLimitError: If rate limited.
        """
        iid = installation_id or self._settings.installation_id
        if not iid:
            msg = (
                "No installation_id provided. Pass it explicitly or set SYN_GITHUB_INSTALLATION_ID."
            )
            raise GitHubAuthError(msg)

        # Return cached token if valid
        cached = self._cached_tokens.get(iid)
        if not force_refresh and cached and not cached.is_expired:
            logger.debug(
                "Using cached installation token (installation_id=%s, expires_in=%ss)",
                iid,
                f"{cached.seconds_until_expiry:.0f}",
            )
            return cached.token

        logger.info("Generating new installation token for installation_id=%s", iid)

        jwt_token = self._generate_jwt()

        try:
            response = await self._http.post(
                f"/app/installations/{iid}/access_tokens",
                headers={"Authorization": f"Bearer {jwt_token}"},
            )

            if response.status_code == 401:
                msg = "JWT authentication failed - check App ID and private key"
                raise GitHubAuthError(msg)

            if response.status_code == 403:
                if "rate limit" in response.text.lower():
                    reset_header = response.headers.get("X-RateLimit-Reset")
                    reset_at = None
                    if reset_header:
                        reset_at = datetime.fromtimestamp(int(reset_header), tz=UTC)
                    raise GitHubRateLimitError("Rate limit exceeded", reset_at=reset_at)
                msg = f"Permission denied: {response.text}"
                raise GitHubAuthError(msg)

            if response.status_code == 404:
                msg = f"Installation {iid} not found"
                raise GitHubAuthError(msg)

            response.raise_for_status()

            data = response.json()
            expires_at = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))

            token = InstallationToken(
                token=data["token"],
                expires_at=expires_at,
                permissions=data.get("permissions", {}),
                repository_selection=data.get("repository_selection", "all"),
            )
            self._cached_tokens[iid] = token

            logger.info(
                "Installation token generated (installation_id=%s, expires_at=%s, permissions=%s)",
                iid,
                expires_at.isoformat(),
                list(token.permissions.keys()),
            )

            return token.token

        except httpx.HTTPError as e:
            msg = f"HTTP error generating token: {e}"
            raise GitHubAuthError(msg) from e

    async def api_get(self, path: str, installation_id: str | None = None) -> dict:
        """Make an authenticated GET request to the GitHub API.

        Args:
            path: API path (e.g., "/repos/owner/repo").
            installation_id: Installation to authenticate as. Falls back to
                SYN_GITHUB_INSTALLATION_ID if not provided.

        Returns:
            Response JSON as dictionary.

        Raises:
            GitHubAppError: On API errors.
        """
        token = await self.get_installation_token(installation_id)

        response = await self._http.get(
            path,
            headers={"Authorization": f"Bearer {token}"},
        )

        self._check_response(response)
        return response.json()

    async def api_post(
        self, path: str, json: dict | None = None, installation_id: str | None = None
    ) -> dict:
        """Make an authenticated POST request to the GitHub API.

        Args:
            path: API path.
            json: Request body.
            installation_id: Installation to authenticate as. Falls back to
                SYN_GITHUB_INSTALLATION_ID if not provided.

        Returns:
            Response JSON as dictionary.

        Raises:
            GitHubAppError: On API errors.
        """
        token = await self.get_installation_token(installation_id)

        response = await self._http.post(
            path,
            headers={"Authorization": f"Bearer {token}"},
            json=json,
        )

        self._check_response(response)
        return response.json()

    async def api_put(
        self, path: str, json: dict | None = None, installation_id: str | None = None
    ) -> dict:
        """Make an authenticated PUT request to the GitHub API.

        Args:
            path: API path.
            json: Request body.
            installation_id: Installation to authenticate as. Falls back to
                SYN_GITHUB_INSTALLATION_ID if not provided.

        Returns:
            Response JSON as dictionary.

        Raises:
            GitHubAppError: On API errors.
        """
        token = await self.get_installation_token(installation_id)

        response = await self._http.put(
            path,
            headers={"Authorization": f"Bearer {token}"},
            json=json,
        )

        self._check_response(response)
        return response.json()

    def _check_response(self, response: httpx.Response) -> None:
        """Check response for errors.

        Raises:
            GitHubRateLimitError: If rate limited.
            GitHubAppError: On other errors.
        """
        if response.status_code == 403 and "rate limit" in response.text.lower():
            reset_header = response.headers.get("X-RateLimit-Reset")
            reset_at = None
            if reset_header:
                reset_at = datetime.fromtimestamp(int(reset_header), tz=UTC)
            raise GitHubRateLimitError("Rate limit exceeded", reset_at=reset_at)

        if response.status_code >= 400:
            msg = f"GitHub API error {response.status_code}: {response.text}"
            raise GitHubAppError(msg)

    async def get_app_info(self) -> dict:
        """Get information about the GitHub App.

        Returns:
            App metadata including name, ID, permissions.
        """
        jwt_token = self._generate_jwt()

        response = await self._http.get(
            "/app",
            headers={"Authorization": f"Bearer {jwt_token}"},
        )

        self._check_response(response)
        return response.json()

    async def get_webhook_config(self) -> dict:
        """Get the GitHub App's webhook configuration.

        Uses App-level JWT auth (not installation tokens).

        Returns:
            Webhook config including url, content_type, insecure_ssl, secret.
        """
        jwt_token = self._generate_jwt()

        response = await self._http.get(
            "/app/hook/config",
            headers={"Authorization": f"Bearer {jwt_token}"},
        )

        self._check_response(response)
        return response.json()

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
        jwt_token = self._generate_jwt()

        payload: dict[str, str] = {
            "url": url,
            "content_type": content_type,
            "insecure_ssl": insecure_ssl,
        }
        if secret is not None:
            payload["secret"] = secret

        response = await self._http.patch(
            "/app/hook/config",
            headers={"Authorization": f"Bearer {jwt_token}"},
            json=payload,
        )

        self._check_response(response)
        return response.json()

    async def list_installations(self) -> list[dict]:
        """List all installations of this GitHub App.

        Returns:
            List of installation metadata.
        """
        jwt_token = self._generate_jwt()

        response = await self._http.get(
            "/app/installations",
            headers={"Authorization": f"Bearer {jwt_token}"},
        )

        self._check_response(response)
        return response.json()

    async def list_accessible_repos(self, installation_id: str | None = None) -> list[dict]:
        """List repositories accessible to an installation.

        Args:
            installation_id: The installation to list repos for. Falls back to
                SYN_GITHUB_INSTALLATION_ID if not provided.

        Returns:
            List of repository metadata.
        """
        token = await self.get_installation_token(installation_id)

        response = await self._http.get(
            "/installation/repositories",
            headers={"Authorization": f"Bearer {token}"},
        )

        self._check_response(response)
        return response.json().get("repositories", [])


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
        msg = (
            "GitHub App not configured. Set SYN_GITHUB_APP_ID and SYN_GITHUB_PRIVATE_KEY."
        )
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
