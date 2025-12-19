"""Tests for refresh_token feature slice."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aef_domain.contexts.github.refresh_token.RefreshTokenCommand import (
    RefreshTokenCommand,
)
from aef_domain.contexts.github.refresh_token.TokenRefreshedEvent import (
    TokenRefreshedEvent,
)


@pytest.mark.unit
class TestRefreshTokenCommand:
    """Tests for RefreshTokenCommand."""

    def test_create_command(self) -> None:
        """Test creating a RefreshTokenCommand."""
        cmd = RefreshTokenCommand(
            installation_id="12345",
            force=True,
        )

        assert cmd.installation_id == "12345"
        assert cmd.force is True
        assert cmd.command_id  # Should be auto-generated

    def test_default_force(self) -> None:
        """Test that force defaults to False."""
        cmd = RefreshTokenCommand(installation_id="12345")
        assert cmd.force is False

    def test_validation_empty_installation_id(self) -> None:
        """Test that empty installation_id raises error."""
        with pytest.raises(ValueError, match="installation_id is required"):
            RefreshTokenCommand(installation_id="")


class TestTokenRefreshedEvent:
    """Tests for TokenRefreshedEvent."""

    def test_create_event(self) -> None:
        """Test creating a TokenRefreshedEvent."""
        expires_at = datetime.now(UTC)
        event = TokenRefreshedEvent(
            installation_id="12345",
            token_hash="abc123def456",
            expires_at=expires_at,
            permissions={"contents": "write"},
        )

        assert event.installation_id == "12345"
        assert event.token_hash == "abc123def456"
        assert event.expires_at == expires_at
        assert event.permissions["contents"] == "write"

    def test_event_is_immutable(self) -> None:
        """Test that event is immutable (frozen)."""
        event = TokenRefreshedEvent(
            installation_id="12345",
            token_hash="abc123",
            expires_at=datetime.now(UTC),
        )

        from pydantic import ValidationError

        with pytest.raises(ValidationError):  # Pydantic raises ValidationError for frozen
            event.installation_id = "changed"  # type: ignore[misc]

    def test_validation_empty_installation_id(self) -> None:
        """Test that empty installation_id raises error."""
        with pytest.raises(ValueError, match="installation_id is required"):
            TokenRefreshedEvent(
                installation_id="",
                token_hash="abc",
                expires_at=datetime.now(UTC),
            )

    def test_validation_empty_token_hash(self) -> None:
        """Test that empty token_hash raises error."""
        with pytest.raises(ValueError, match="token_hash is required"):
            TokenRefreshedEvent(
                installation_id="123",
                token_hash="",
                expires_at=datetime.now(UTC),
            )

    def test_validation_naive_datetime(self) -> None:
        """Test that naive datetime raises error."""
        with pytest.raises(ValueError, match="expires_at must be timezone-aware"):
            TokenRefreshedEvent(
                installation_id="123",
                token_hash="abc",
                expires_at=datetime.now(),  # No timezone!
            )
