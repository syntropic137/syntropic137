"""Tests for GitHub context value objects."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aef_domain.contexts.github._shared.value_objects import (
    GitHubAccount,
    InstallationId,
    InstallationToken,
    RepositoryPermission,
)


class TestInstallationId:
    """Tests for InstallationId value object."""

    def test_create_valid(self) -> None:
        """Test creating a valid InstallationId."""
        id_ = InstallationId(value="12345")
        assert id_.value == "12345"
        assert str(id_) == "12345"

    def test_validation_empty(self) -> None:
        """Test that empty value raises error."""
        with pytest.raises(ValueError, match="cannot be empty"):
            InstallationId(value="")

    def test_validation_non_numeric(self) -> None:
        """Test that non-numeric value raises error."""
        with pytest.raises(ValueError, match="must be numeric"):
            InstallationId(value="abc")

    def test_frozen(self) -> None:
        """Test that InstallationId is immutable."""
        id_ = InstallationId(value="12345")
        with pytest.raises(AttributeError):
            id_.value = "67890"  # type: ignore


class TestInstallationToken:
    """Tests for InstallationToken value object."""

    def test_create_valid(self) -> None:
        """Test creating a valid InstallationToken."""
        expires_at = datetime.now(UTC) + timedelta(hours=1)
        token = InstallationToken(token="ghs_xxx", expires_at=expires_at)

        assert token.token == "ghs_xxx"
        assert token.expires_at == expires_at
        assert not token.is_expired
        assert not token.is_expiring_soon

    def test_is_expired(self) -> None:
        """Test expired token detection."""
        expires_at = datetime.now(UTC) - timedelta(minutes=1)
        token = InstallationToken(token="ghs_xxx", expires_at=expires_at)

        assert token.is_expired

    def test_is_expiring_soon(self) -> None:
        """Test expiring soon detection (within 5 minutes)."""
        expires_at = datetime.now(UTC) + timedelta(minutes=3)
        token = InstallationToken(token="ghs_xxx", expires_at=expires_at)

        assert token.is_expiring_soon

    def test_token_hash(self) -> None:
        """Test token hash generation."""
        expires_at = datetime.now(UTC) + timedelta(hours=1)
        token = InstallationToken(token="ghs_secret_token", expires_at=expires_at)

        # Hash should be consistent and 12 chars
        assert len(token.token_hash) == 12
        hash1 = token.token_hash
        hash2 = token.token_hash
        assert hash1 == hash2  # Should be consistent across accesses

    def test_safe_repr(self) -> None:
        """Test that repr doesn't expose the token."""
        expires_at = datetime.now(UTC) + timedelta(hours=1)
        token = InstallationToken(token="ghs_secret_token", expires_at=expires_at)

        repr_str = repr(token)
        assert "ghs_secret_token" not in repr_str
        assert "hash=" in repr_str

    def test_validation_empty_token(self) -> None:
        """Test that empty token raises error."""
        with pytest.raises(ValueError, match="cannot be empty"):
            InstallationToken(
                token="",
                expires_at=datetime.now(UTC),
            )

    def test_validation_naive_datetime(self) -> None:
        """Test that naive datetime raises error."""
        with pytest.raises(ValueError, match="timezone-aware"):
            InstallationToken(
                token="ghs_xxx",
                expires_at=datetime.now(),  # No timezone!
            )


class TestRepositoryPermission:
    """Tests for RepositoryPermission value object."""

    def test_create_valid(self) -> None:
        """Test creating a valid permission."""
        perm = RepositoryPermission(name="contents", level="write")
        assert perm.name == "contents"
        assert perm.level == "write"

    def test_valid_levels(self) -> None:
        """Test all valid permission levels."""
        for level in ["read", "write", "admin"]:
            perm = RepositoryPermission(name="test", level=level)
            assert perm.level == level

    def test_invalid_level(self) -> None:
        """Test that invalid level raises error."""
        with pytest.raises(ValueError, match="Invalid permission level"):
            RepositoryPermission(name="contents", level="invalid")


class TestGitHubAccount:
    """Tests for GitHubAccount value object."""

    def test_create_user(self) -> None:
        """Test creating a User account."""
        account = GitHubAccount(id=123, login="testuser", account_type="User")
        assert account.id == 123
        assert account.login == "testuser"
        assert account.account_type == "User"

    def test_create_organization(self) -> None:
        """Test creating an Organization account."""
        account = GitHubAccount(id=456, login="testorg", account_type="Organization")
        assert account.account_type == "Organization"

    def test_invalid_account_type(self) -> None:
        """Test that invalid account_type raises error."""
        with pytest.raises(ValueError, match="Invalid account type"):
            GitHubAccount(id=123, login="test", account_type="Bot")
