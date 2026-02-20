"""Tests for GitHubAppClient."""

from __future__ import annotations

import base64
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest

from syn_adapters.github.client import (
    JWT_ALGORITHM,
    GitHubAppClient,
    GitHubAuthError,
    GitHubRateLimitError,
    InstallationToken,
    reset_github_client,
)

# Test RSA key (PKCS8 format, DO NOT USE IN PRODUCTION)
TEST_PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDM/odlKTkfeBSR
vt8MVhBUqnxH4g8eeVdGNNPsk3nyW/Fblh95pH58xhhl/6Ppu5D87loeMdSHsY4H
EpsC41qHTh7siIB7YVde94f2RZzM6xcgv5S2oxQupS+sL1N4n3ec1uLFAMAU3UrG
vSw6vg6C+v1/4tTwOF3/k3sgWnBshejRTIj4uQ7ZcP/EHZclH0bzZ4Zwo6UostWY
jR7KLMPVaOrIdMPq35Qy65Da4BdWJDq4onh7vu26zAcQK4TmkEmLZ28Yfh4CwXIj
5JR1f5yOwoIhYuUPPw7I4wOTO8G4vA7345ShITUJpyd08C4yfBt0WQ5MaPqt+/Gw
DkfqlV2NAgMBAAECggEAAnwxcwIBbca8ZRntxU4Dy6r3b72nVkS9UJ4SVaNiDpSb
w/L5dbWPTP7vy8jCGXLLKq3PDN+oxm5aHO7WTz4nWk2RpWdwO06uSvnwPYWRhZBy
CtUXvfETLQ+WmN1IA0XXouCeBipgqcAXCHrBnwKv1VmqmhLLZxAf35nPm9BM3Zvq
bCmPS1+XvH1f1G1gxzXFS7FKXkznSL2BmaZe158/w4VxukktCTFri0ufoPB0x6qL
s16piCXYttRuOkda4x/grCygZQ6eXtQdcVReZNqomAXGNTyxIi2qDJeqDzwNYoZA
vc57KwxGGaRN0uujZSjk2MVn8F69zwtgQ78AGk2WQQKBgQDuFWOFSYT7T7J8S13F
BGQCFVYsmCFdTrD7muf5+AbrstL7kn8K8glvcwExlek4xvfkA+RmuTnOzo64OO81
F2DxwdeVI/x6fuEZvaWLKTLb5La/umKZA1JJD+BeQE+DJct5VshEHjW64AjvqTsk
BuykgxZoTqFGz07JIquaIJ5z4QKBgQDca68w0OlJe4f0y1SeOQsD8/NdhZys0du4
bhuPef4WZYoX5ZkkolX8kH7wFbuC2X//Fzkv8rr5pm7pHUpvjdncM3lvZ18vX6G/
hrCLj/K1z8mhiGH4T/o7aN799zdxdZLlMoPhqPW9iGFUj8mPT2TuG99Woy3yxVKt
bT1ZwQrfLQKBgE1LmmTiio8Av+TEnyvgkgtvG+wcc/CUJLd7AkdQdAa/punQFPjb
vZ52SvPrRK2PQ1m+vb9v8UmoHAPJUDf/YBT9Jt2fsk+es7wkqwM0G/PyHDbA71PY
FTXtNp3C6U2dzqKVPy2GVVFXfO86FR5MNTXv7S1uIcQYd+6rF+VRI8BhAoGAXNZS
JHppN5T7D2SwkC+wbwrJvuMuuS9unsBphUW5eg9sWWJP3TkuhEEL5e0RXCxll7hd
Us+mZs3tuuumVVPmpbNce0qLsbVSuAtvwmhvrpoE7680rFRrLaie+1KrnHML2tMq
7tmuHxUZAXfKSj0DYrKEn8X87Vqk1vzCsVH4VUUCgYEAq5TdSZVZ6SWvAEyRB/1E
Vf/gky72ghuF+cbX/VAZzPr03HkcPRF4qFlgOTydQ+kTJbR9QrywbEWY+aeVtGW+
+/F9OPEBl28srJ87uqr3Z5r+1NGDobHvylka8sSDKczcv+Ns5pCiWXW9yxgwTGD/
uknUDJfMkmaPfBacq//Glj8=
-----END PRIVATE KEY-----
"""

TEST_PRIVATE_KEY_B64 = base64.b64encode(TEST_PRIVATE_KEY.encode()).decode()


@pytest.fixture
def mock_github_settings() -> MagicMock:
    """Create mock GitHub settings."""
    settings = MagicMock()
    settings.app_id = "12345"
    settings.app_name = "test-app"
    settings.installation_id = "67890"
    settings.private_key = MagicMock()
    settings.private_key.get_secret_value.return_value = TEST_PRIVATE_KEY_B64
    settings.is_configured = True
    settings.bot_name = "test-app[bot]"
    settings.bot_email = "12345+test-app[bot]@users.noreply.github.com"
    return settings


@pytest.mark.unit
class TestInstallationToken:
    """Tests for InstallationToken dataclass."""

    def test_is_expired_when_expired(self) -> None:
        """Token should be expired when past expiry time."""
        token = InstallationToken(
            token="test",
            expires_at=datetime.now(UTC) - timedelta(minutes=5),
            permissions={},
            repository_selection="all",
        )
        assert token.is_expired is True

    def test_is_expired_when_near_expiry(self) -> None:
        """Token should be expired when within refresh threshold."""
        token = InstallationToken(
            token="test",
            # Expires in 5 minutes, but threshold is 10 minutes
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            permissions={},
            repository_selection="all",
        )
        assert token.is_expired is True

    def test_is_not_expired_when_fresh(self) -> None:
        """Token should not be expired when well before expiry."""
        token = InstallationToken(
            token="test",
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
            permissions={},
            repository_selection="all",
        )
        assert token.is_expired is False

    def test_seconds_until_expiry(self) -> None:
        """Should calculate remaining time correctly."""
        expires_in = 1800  # 30 minutes
        token = InstallationToken(
            token="test",
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
            permissions={},
            repository_selection="all",
        )
        # Allow 1 second tolerance for test execution time
        assert abs(token.seconds_until_expiry - expires_in) < 1


class TestGitHubAppClient:
    """Tests for GitHubAppClient."""

    def test_init_requires_configured_settings(self) -> None:
        """Should raise if settings not configured."""
        settings = MagicMock()
        settings.is_configured = False

        with pytest.raises(ValueError, match="not fully configured"):
            GitHubAppClient(settings)

    def test_init_success(self, mock_github_settings: MagicMock) -> None:
        """Should initialize with valid settings."""
        client = GitHubAppClient(mock_github_settings)
        assert client.app_id == "12345"
        assert client.bot_username == "test-app[bot]"

    def test_generate_jwt(self, mock_github_settings: MagicMock) -> None:
        """Should generate valid JWT."""
        client = GitHubAppClient(mock_github_settings)
        jwt_token = client._generate_jwt()

        # Decode without verification (just checking payload structure)
        decoded = jwt.decode(
            jwt_token,
            options={"verify_signature": False},
            algorithms=[JWT_ALGORITHM],
        )

        assert decoded["iss"] == "12345"
        assert "iat" in decoded
        assert "exp" in decoded

        # Check timing
        now = int(time.time())
        assert decoded["iat"] <= now  # Issued in past (with clock skew)
        assert decoded["exp"] > now  # Expires in future

    def test_get_private_key_caches(self, mock_github_settings: MagicMock) -> None:
        """Private key should be decoded and cached."""
        client = GitHubAppClient(mock_github_settings)

        key1 = client._get_private_key()
        key2 = client._get_private_key()

        assert key1 == key2
        assert key1.startswith("-----BEGIN PRIVATE KEY-----")

        # Should only decode once
        mock_github_settings.private_key.get_secret_value.assert_called_once()

    def test_get_private_key_invalid_base64(self, mock_github_settings: MagicMock) -> None:
        """Should raise on invalid base64."""
        mock_github_settings.private_key.get_secret_value.return_value = "not-valid-base64!!!"
        client = GitHubAppClient(mock_github_settings)

        with pytest.raises(GitHubAuthError, match="Failed to decode"):
            client._get_private_key()

    @pytest.mark.asyncio
    async def test_get_installation_token_success(self, mock_github_settings: MagicMock) -> None:
        """Should fetch and cache installation token."""
        client = GitHubAppClient(mock_github_settings)

        expires_at = datetime.now(UTC) + timedelta(hours=1)

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "token": "ghs_test_token_12345",
            "expires_at": expires_at.isoformat(),
            "permissions": {"contents": "write", "pull_requests": "write"},
            "repository_selection": "selected",
        }

        with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            token = await client.get_installation_token(installation_id="67890")

            assert token == "ghs_test_token_12345"
            cached = client._cached_tokens.get("67890")
            assert cached is not None
            assert cached.permissions == {
                "contents": "write",
                "pull_requests": "write",
            }

    @pytest.mark.asyncio
    async def test_get_installation_token_uses_cache(self, mock_github_settings: MagicMock) -> None:
        """Should return cached token if still valid."""
        client = GitHubAppClient(mock_github_settings)

        # Pre-cache a token
        client._cached_tokens["67890"] = InstallationToken(
            token="cached_token",
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
            permissions={},
            repository_selection="all",
        )

        with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
            token = await client.get_installation_token(installation_id="67890")

            assert token == "cached_token"
            mock_post.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_installation_token_refreshes_expired(
        self, mock_github_settings: MagicMock
    ) -> None:
        """Should refresh token when expired."""
        client = GitHubAppClient(mock_github_settings)

        # Pre-cache an expired token
        client._cached_token = InstallationToken(
            token="expired_token",
            expires_at=datetime.now(UTC) - timedelta(minutes=5),
            permissions={},
            repository_selection="all",
        )

        expires_at = datetime.now(UTC) + timedelta(hours=1)
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "token": "new_token",
            "expires_at": expires_at.isoformat(),
            "permissions": {},
            "repository_selection": "all",
        }

        with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            token = await client.get_installation_token()

            assert token == "new_token"
            mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_installation_token_auth_error(self, mock_github_settings: MagicMock) -> None:
        """Should raise on 401 response."""
        client = GitHubAppClient(mock_github_settings)

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Bad credentials"

        with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            with pytest.raises(GitHubAuthError, match="JWT authentication failed"):
                await client.get_installation_token()

    @pytest.mark.asyncio
    async def test_get_installation_token_rate_limit(self, mock_github_settings: MagicMock) -> None:
        """Should raise rate limit error with reset time."""
        client = GitHubAppClient(mock_github_settings)

        reset_timestamp = int(time.time()) + 3600

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Rate limit exceeded"
        mock_response.headers = {"X-RateLimit-Reset": str(reset_timestamp)}

        with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            with pytest.raises(GitHubRateLimitError) as exc_info:
                await client.get_installation_token()

            assert exc_info.value.reset_at is not None

    @pytest.mark.asyncio
    async def test_list_accessible_repos(self, mock_github_settings: MagicMock) -> None:
        """Should list accessible repositories."""
        client = GitHubAppClient(mock_github_settings)

        # Mock token fetch
        client._cached_tokens["67890"] = InstallationToken(
            token="test_token",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            permissions={},
            repository_selection="all",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "repositories": [
                {"full_name": "org/repo1", "private": True},
                {"full_name": "org/repo2", "private": False},
            ]
        }

        with patch.object(client._http, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            repos = await client.list_accessible_repos()

            assert len(repos) == 2
            assert repos[0]["full_name"] == "org/repo1"


class TestSingletonClient:
    """Tests for get_github_client singleton."""

    def teardown_method(self) -> None:
        """Reset singleton after each test."""
        reset_github_client()

    def test_raises_when_not_configured(self) -> None:
        """Should raise if GitHub not configured."""
        # Import inside function to patch correctly
        from syn_adapters.github.client import get_github_client

        with patch("syn_shared.settings.get_settings") as mock_get_settings:
            mock_settings = MagicMock()
            mock_settings.github.is_configured = False
            mock_get_settings.return_value = mock_settings

            with pytest.raises(ValueError, match="not configured"):
                get_github_client()
