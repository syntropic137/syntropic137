"""Tests for GitHub webhook endpoints.

These tests mock syn_api.v1.github to validate the dashboard's
thin-wrapper webhook endpoint.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from syn_api.types import Err, GitHubError, Ok, WebhookResult
from syn_dashboard.main import app

API_MODULE = "syn_api.v1.github"


@pytest.fixture
def client() -> TestClient:
    """Create a test client."""
    return TestClient(app)


@pytest.mark.unit
class TestGitHubWebhook:
    """Tests for the /webhooks/github endpoint."""

    def test_ping_event(self, client: TestClient) -> None:
        """Test handling ping event from GitHub (handled locally, not via syn_api)."""
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
        with patch(f"{API_MODULE}.verify_and_process_webhook", new_callable=AsyncMock) as mock:
            mock.return_value = Ok(
                WebhookResult(
                    status="processed",
                    event="installation",
                    triggers_fired=[],
                    deferred=[],
                )
            )
            response = client.post(
                "/webhooks/github",
                json={"action": "created", "installation": {"id": 12345}},
                headers={
                    "X-GitHub-Event": "installation",
                    "X-GitHub-Delivery": "test-delivery-456",
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "processed"
            assert data["event"] == "installation"

    def test_webhook_with_triggers(self, client: TestClient) -> None:
        """Test webhook that fires triggers."""
        with patch(f"{API_MODULE}.verify_and_process_webhook", new_callable=AsyncMock) as mock:
            mock.return_value = Ok(
                WebhookResult(
                    status="processed",
                    event="push",
                    triggers_fired=["trigger-1", "trigger-2"],
                    deferred=["trigger-3"],
                )
            )
            response = client.post(
                "/webhooks/github",
                json={"ref": "refs/heads/main"},
                headers={
                    "X-GitHub-Event": "push",
                    "X-GitHub-Delivery": "test-delivery-push",
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "processed"
            assert len(data["triggers"]) == 2
            assert len(data["deferred"]) == 1

    def test_invalid_signature_rejected(self, client: TestClient) -> None:
        """Test that invalid signature returns 401."""
        with patch(f"{API_MODULE}.verify_and_process_webhook", new_callable=AsyncMock) as mock:
            mock.return_value = Err(
                GitHubError.INVALID_SIGNATURE,
                message="Invalid signature",
            )
            response = client.post(
                "/webhooks/github",
                json={"zen": "Test"},
                headers={
                    "X-GitHub-Event": "push",
                    "X-GitHub-Delivery": "test-delivery",
                    "X-Hub-Signature-256": "sha256=invalid",
                },
            )

            assert response.status_code == 401
            assert "Invalid signature" in response.json()["detail"]

    def test_invalid_payload_rejected(self, client: TestClient) -> None:
        """Test that invalid payload returns 400."""
        with patch(f"{API_MODULE}.verify_and_process_webhook", new_callable=AsyncMock) as mock:
            mock.return_value = Err(
                GitHubError.INVALID_PAYLOAD,
                message="Invalid payload format",
            )
            response = client.post(
                "/webhooks/github",
                json={"bad": "data"},
                headers={
                    "X-GitHub-Event": "push",
                    "X-GitHub-Delivery": "test-delivery",
                },
            )

            assert response.status_code == 400
            assert "Invalid payload" in response.json()["detail"]

    def test_processing_error_returns_500(self, client: TestClient) -> None:
        """Test that processing failure returns 500."""
        with patch(f"{API_MODULE}.verify_and_process_webhook", new_callable=AsyncMock) as mock:
            mock.return_value = Err(
                GitHubError.PROCESSING_FAILED,
                message="Internal error processing webhook",
            )
            response = client.post(
                "/webhooks/github",
                json={"data": "test"},
                headers={
                    "X-GitHub-Event": "push",
                    "X-GitHub-Delivery": "test-delivery",
                },
            )

            assert response.status_code == 500

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
