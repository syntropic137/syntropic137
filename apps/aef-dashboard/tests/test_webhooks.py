"""Tests for GitHub webhook endpoints."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from aef_dashboard.main import create_app
from aef_shared.settings.github import reset_github_settings


@pytest.fixture
def client() -> TestClient:
    """Create a test client."""
    app = create_app()
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_settings() -> None:
    """Reset settings before each test."""
    reset_github_settings()


@pytest.fixture(autouse=True)
def development_environment() -> None:
    """Set development environment for tests without signature."""
    import os

    original = os.environ.get("AEF_ENVIRONMENT")
    os.environ["AEF_ENVIRONMENT"] = "development"
    yield
    if original is None:
        os.environ.pop("AEF_ENVIRONMENT", None)
    else:
        os.environ["AEF_ENVIRONMENT"] = original


@pytest.mark.unit
class TestGitHubWebhook:
    """Tests for the /webhooks/github endpoint."""

    def test_ping_event(self, client: TestClient) -> None:
        """Test handling ping event from GitHub."""
        payload = {"zen": "Keep it simple."}

        response = client.post(
            "/webhooks/github",
            json=payload,
            headers={
                "X-GitHub-Event": "ping",
                "X-GitHub-Delivery": "test-delivery-123",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pong"
        assert data["zen"] == "Keep it simple."

    def test_installation_created_event(self, client: TestClient) -> None:
        """Test handling installation created event."""
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

        response = client.post(
            "/webhooks/github",
            json=payload,
            headers={
                "X-GitHub-Event": "installation",
                "X-GitHub-Delivery": "test-delivery-456",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "processed"
        assert data["action"] == "created"
        assert data["installation_id"] == "12345"

    def test_installation_deleted_event(self, client: TestClient) -> None:
        """Test handling installation deleted event."""
        payload = {
            "action": "deleted",
            "installation": {
                "id": 12345,
                "account": {
                    "login": "test-org",
                },
            },
        }

        response = client.post(
            "/webhooks/github",
            json=payload,
            headers={
                "X-GitHub-Event": "installation",
                "X-GitHub-Delivery": "test-delivery-789",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "processed"
        assert data["action"] == "deleted"

    def test_installation_suspend_event(self, client: TestClient) -> None:
        """Test handling installation suspend event."""
        payload = {
            "action": "suspend",
            "installation": {
                "id": 12345,
            },
        }

        response = client.post(
            "/webhooks/github",
            json=payload,
            headers={
                "X-GitHub-Event": "installation",
                "X-GitHub-Delivery": "test-delivery-suspend",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "processed"
        assert data["action"] == "suspend"
        assert data["installation_id"] == "12345"

    def test_installation_repos_event(self, client: TestClient) -> None:
        """Test handling installation_repositories event."""
        payload = {
            "action": "added",
            "installation": {
                "id": 12345,
            },
            "repositories_added": [
                {"full_name": "test-org/new-repo"},
            ],
            "repositories_removed": [],
        }

        response = client.post(
            "/webhooks/github",
            json=payload,
            headers={
                "X-GitHub-Event": "installation_repositories",
                "X-GitHub-Delivery": "test-delivery-repos",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "processed"
        assert data["repos_added"] == 1
        assert data["repos_removed"] == 0

    def test_unknown_event_ignored(self, client: TestClient) -> None:
        """Test that unknown events are ignored."""
        response = client.post(
            "/webhooks/github",
            json={"some": "data"},
            headers={
                "X-GitHub-Event": "unknown_event",
                "X-GitHub-Delivery": "test-delivery-unknown",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ignored"
        assert data["event"] == "unknown_event"

    def test_unknown_installation_action_ignored(self, client: TestClient) -> None:
        """Test that unknown installation actions are ignored."""
        payload = {
            "action": "some_future_action",
            "installation": {"id": 12345},
        }

        response = client.post(
            "/webhooks/github",
            json=payload,
            headers={
                "X-GitHub-Event": "installation",
                "X-GitHub-Delivery": "test-delivery-action",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ignored"

    def test_missing_github_event_header(self, client: TestClient) -> None:
        """Test that missing X-GitHub-Event header returns 422."""
        response = client.post(
            "/webhooks/github",
            json={},
            headers={
                "X-GitHub-Delivery": "test-delivery",
            },
        )

        assert response.status_code == 422

    def test_invalid_json_payload(self, client: TestClient) -> None:
        """Test that invalid JSON returns 400."""
        response = client.post(
            "/webhooks/github",
            content=b"not valid json",
            headers={
                "X-GitHub-Event": "ping",
                "X-GitHub-Delivery": "test-delivery",
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert "Invalid JSON" in data["detail"]


class TestWebhookSignatureVerification:
    """Tests for webhook signature verification."""

    def test_valid_signature_accepted(self, client: TestClient) -> None:
        """Test that valid signature is accepted."""
        # Configure webhook secret
        with mock.patch.dict(
            "os.environ",
            {"AEF_GITHUB_WEBHOOK_SECRET": "test-secret"},
        ):
            reset_github_settings()

            payload = json.dumps({"zen": "Test"}).encode()
            signature = "sha256=" + hmac.new(b"test-secret", payload, hashlib.sha256).hexdigest()

            response = client.post(
                "/webhooks/github",
                content=payload,
                headers={
                    "X-GitHub-Event": "ping",
                    "X-GitHub-Delivery": "test-delivery",
                    "X-Hub-Signature-256": signature,
                    "Content-Type": "application/json",
                },
            )

            assert response.status_code == 200

    def test_invalid_signature_rejected(self, client: TestClient) -> None:
        """Test that invalid signature is rejected."""
        with mock.patch.dict(
            "os.environ",
            {"AEF_GITHUB_WEBHOOK_SECRET": "test-secret"},
        ):
            reset_github_settings()

            response = client.post(
                "/webhooks/github",
                json={"zen": "Test"},
                headers={
                    "X-GitHub-Event": "ping",
                    "X-GitHub-Delivery": "test-delivery",
                    "X-Hub-Signature-256": "sha256=invalid",
                },
            )

            assert response.status_code == 401
            assert "Invalid signature" in response.json()["detail"]

    def test_missing_signature_when_secret_configured(self, client: TestClient) -> None:
        """Test that missing signature is rejected when secret is configured."""
        with mock.patch.dict(
            "os.environ",
            {"AEF_GITHUB_WEBHOOK_SECRET": "test-secret"},
        ):
            reset_github_settings()

            response = client.post(
                "/webhooks/github",
                json={"zen": "Test"},
                headers={
                    "X-GitHub-Event": "ping",
                    "X-GitHub-Delivery": "test-delivery",
                },
            )

            assert response.status_code == 401
            assert "Missing X-Hub-Signature-256" in response.json()["detail"]

    def test_no_secret_in_dev_mode_accepts_without_signature(self, client: TestClient) -> None:
        """Test that in development mode without secret, requests are accepted."""
        # AEF_ENVIRONMENT is set to 'development' by fixture
        response = client.post(
            "/webhooks/github",
            json={"zen": "Test"},
            headers={
                "X-GitHub-Event": "ping",
                "X-GitHub-Delivery": "test-delivery",
            },
        )

        assert response.status_code == 200

    def test_no_secret_in_production_rejects(self, client: TestClient) -> None:
        """Test that in production mode without secret, requests are rejected."""
        with mock.patch.dict("os.environ", {"AEF_ENVIRONMENT": "production"}):
            reset_github_settings()

            response = client.post(
                "/webhooks/github",
                json={"zen": "Test"},
                headers={
                    "X-GitHub-Event": "ping",
                    "X-GitHub-Delivery": "test-delivery",
                },
            )

            assert response.status_code == 500
            assert "not configured" in response.json()["detail"]
