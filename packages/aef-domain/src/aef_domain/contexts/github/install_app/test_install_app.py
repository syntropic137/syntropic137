"""Tests for install_app feature slice."""

from __future__ import annotations

import pytest

from aef_domain.contexts.github.install_app.AppInstalledEvent import (
    AppInstalledEvent,
)
from aef_domain.contexts.github.install_app.InstallationRevokedEvent import (
    InstallationRevokedEvent,
)


@pytest.mark.unit
class TestAppInstalledEvent:
    """Tests for AppInstalledEvent."""

    def test_create_event(self) -> None:
        """Test creating an AppInstalledEvent."""
        event = AppInstalledEvent(
            installation_id="12345",
            account_id=67890,
            account_name="test-org",
            account_type="Organization",
            repositories=("test-org/repo1", "test-org/repo2"),
            permissions={"contents": "write", "pull_requests": "write"},
        )

        assert event.installation_id == "12345"
        assert event.account_id == 67890
        assert event.account_name == "test-org"
        assert event.account_type == "Organization"
        assert len(event.repositories) == 2
        assert event.permissions["contents"] == "write"

    def test_event_is_immutable(self) -> None:
        """Test that event is immutable (frozen)."""
        event = AppInstalledEvent(
            installation_id="12345",
            account_id=67890,
            account_name="test-org",
            account_type="Organization",
        )

        from pydantic import ValidationError

        with pytest.raises(ValidationError):  # Pydantic raises ValidationError for frozen
            event.installation_id = "changed"  # type: ignore[misc]

    def test_from_webhook(self) -> None:
        """Test creating event from webhook payload."""
        payload = {
            "action": "created",
            "installation": {
                "id": 12345,
                "account": {
                    "id": 67890,
                    "login": "test-org",
                    "type": "Organization",
                },
                "permissions": {
                    "contents": "write",
                    "metadata": "read",
                },
            },
            "repositories": [
                {"full_name": "test-org/repo1"},
                {"full_name": "test-org/repo2"},
            ],
        }

        event = AppInstalledEvent.from_webhook(payload)

        assert event.installation_id == "12345"
        assert event.account_id == 67890
        assert event.account_name == "test-org"
        assert event.account_type == "Organization"
        assert event.repositories == ("test-org/repo1", "test-org/repo2")

    def test_validation_empty_installation_id(self) -> None:
        """Test that empty installation_id raises error."""
        with pytest.raises(ValueError, match="installation_id is required"):
            AppInstalledEvent(
                installation_id="",
                account_id=123,
                account_name="test",
                account_type="User",
            )

    def test_validation_invalid_account_type(self) -> None:
        """Test that invalid account_type raises error."""
        with pytest.raises(ValueError, match="Invalid account_type"):
            AppInstalledEvent(
                installation_id="123",
                account_id=123,
                account_name="test",
                account_type="InvalidType",
            )

    def test_extra_fields_forbidden(self) -> None:
        """Test that extra fields are rejected (type safety)."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AppInstalledEvent(
                installation_id="123",
                account_id=123,
                account_name="test",
                account_type="User",
                unknown_field="bad",  # type: ignore[call-arg]
            )


@pytest.mark.unit
class TestInstallationRevokedEvent:
    """Tests for InstallationRevokedEvent."""

    def test_create_event(self) -> None:
        """Test creating an InstallationRevokedEvent."""
        event = InstallationRevokedEvent(
            installation_id="12345",
            account_name="test-org",
        )

        assert event.installation_id == "12345"
        assert event.account_name == "test-org"

    def test_from_webhook(self) -> None:
        """Test creating event from webhook payload."""
        payload = {
            "action": "deleted",
            "installation": {
                "id": 12345,
                "account": {
                    "login": "test-org",
                },
            },
        }

        event = InstallationRevokedEvent.from_webhook(payload)

        assert event.installation_id == "12345"
        assert event.account_name == "test-org"

    def test_validation_empty_installation_id(self) -> None:
        """Test that empty installation_id raises error."""
        with pytest.raises(ValueError, match="installation_id is required"):
            InstallationRevokedEvent(
                installation_id="",
                account_name="test",
            )
