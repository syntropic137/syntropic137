"""Tests for API endpoints."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ui_feedback.api import feedback as feedback_api
from ui_feedback.api import media as media_api
from ui_feedback.api import stats as stats_api
from ui_feedback.storage.memory import InMemoryFeedbackStorage


@pytest.fixture
def storage() -> InMemoryFeedbackStorage:
    """Create a fresh in-memory storage for each test."""
    return InMemoryFeedbackStorage()


@pytest.fixture
def app(storage: InMemoryFeedbackStorage) -> FastAPI:
    """Create a test FastAPI app."""
    app = FastAPI()

    def get_storage() -> InMemoryFeedbackStorage:
        return storage

    app.dependency_overrides[feedback_api.get_storage] = get_storage
    app.dependency_overrides[media_api.get_storage] = get_storage
    app.dependency_overrides[stats_api.get_storage] = get_storage

    app.include_router(feedback_api.router, prefix="/api")
    app.include_router(media_api.router, prefix="/api")
    app.include_router(stats_api.router, prefix="/api")

    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def sample_feedback_data() -> dict:
    """Sample feedback data for API tests."""
    return {
        "url": "http://localhost:3000/dashboard",
        "route": "/dashboard",
        "viewport_width": 1920,
        "viewport_height": 1080,
        "click_x": 500,
        "click_y": 300,
        "css_selector": "div.card > button",
        "component_name": "DashboardCard",
        "feedback_type": "bug",
        "comment": "Button doesn't work on click",
        "priority": "high",
        "app_name": "test-app",
        "app_version": "1.0.0",
    }


class TestFeedbackAPI:
    """Tests for feedback API endpoints."""

    def test_create_feedback(self, client: TestClient, sample_feedback_data: dict) -> None:
        """Test creating feedback via API."""
        response = client.post("/api/feedback", json=sample_feedback_data)

        assert response.status_code == 201
        data = response.json()
        assert data["url"] == sample_feedback_data["url"]
        assert data["status"] == "open"
        assert "id" in data

    def test_get_feedback(self, client: TestClient, sample_feedback_data: dict) -> None:
        """Test getting feedback via API."""
        # Create first
        create_response = client.post("/api/feedback", json=sample_feedback_data)
        feedback_id = create_response.json()["id"]

        # Get
        response = client.get(f"/api/feedback/{feedback_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == feedback_id
        assert data["media"] == []

    def test_get_feedback_not_found(self, client: TestClient) -> None:
        """Test getting non-existent feedback."""
        response = client.get("/api/feedback/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404

    def test_list_feedback(self, client: TestClient, sample_feedback_data: dict) -> None:
        """Test listing feedback via API."""
        client.post("/api/feedback", json=sample_feedback_data)
        client.post("/api/feedback", json=sample_feedback_data)

        response = client.get("/api/feedback")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

    def test_list_feedback_filter_status(
        self, client: TestClient, sample_feedback_data: dict
    ) -> None:
        """Test filtering feedback by status."""
        create_response = client.post("/api/feedback", json=sample_feedback_data)
        feedback_id = create_response.json()["id"]
        client.post("/api/feedback", json=sample_feedback_data)

        # Update one to resolved
        client.patch(f"/api/feedback/{feedback_id}", json={"status": "resolved"})

        response = client.get("/api/feedback?status=resolved")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1

    def test_update_feedback(self, client: TestClient, sample_feedback_data: dict) -> None:
        """Test updating feedback via API."""
        create_response = client.post("/api/feedback", json=sample_feedback_data)
        feedback_id = create_response.json()["id"]

        response = client.patch(
            f"/api/feedback/{feedback_id}",
            json={
                "status": "in_progress",
                "assigned_to": "dev@example.com",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "in_progress"
        assert data["assigned_to"] == "dev@example.com"

    def test_delete_feedback(self, client: TestClient, sample_feedback_data: dict) -> None:
        """Test deleting feedback via API."""
        create_response = client.post("/api/feedback", json=sample_feedback_data)
        feedback_id = create_response.json()["id"]

        response = client.delete(f"/api/feedback/{feedback_id}")
        assert response.status_code == 204

        # Verify deleted
        get_response = client.get(f"/api/feedback/{feedback_id}")
        assert get_response.status_code == 404


class TestMediaAPI:
    """Tests for media API endpoints."""

    def test_upload_screenshot(self, client: TestClient, sample_feedback_data: dict) -> None:
        """Test uploading a screenshot."""
        create_response = client.post("/api/feedback", json=sample_feedback_data)
        feedback_id = create_response.json()["id"]

        response = client.post(
            f"/api/feedback/{feedback_id}/media",
            data={"media_type": "screenshot"},
            files={"file": ("screenshot.png", b"fake image data", "image/png")},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["media_type"] == "screenshot"
        assert data["mime_type"] == "image/png"

    def test_upload_voice_note(self, client: TestClient, sample_feedback_data: dict) -> None:
        """Test uploading a voice note."""
        create_response = client.post("/api/feedback", json=sample_feedback_data)
        feedback_id = create_response.json()["id"]

        response = client.post(
            f"/api/feedback/{feedback_id}/media",
            data={"media_type": "voice_note"},
            files={"file": ("recording.webm", b"fake audio data", "audio/webm")},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["media_type"] == "voice_note"

    def test_get_media(self, client: TestClient, sample_feedback_data: dict) -> None:
        """Test downloading media."""
        create_response = client.post("/api/feedback", json=sample_feedback_data)
        feedback_id = create_response.json()["id"]

        upload_response = client.post(
            f"/api/feedback/{feedback_id}/media",
            data={"media_type": "screenshot"},
            files={"file": ("test.png", b"test data", "image/png")},
        )
        media_id = upload_response.json()["id"]

        response = client.get(f"/api/feedback/{feedback_id}/media/{media_id}")

        assert response.status_code == 200
        assert response.content == b"test data"
        assert response.headers["content-type"] == "image/png"

    def test_delete_media(self, client: TestClient, sample_feedback_data: dict) -> None:
        """Test deleting media."""
        create_response = client.post("/api/feedback", json=sample_feedback_data)
        feedback_id = create_response.json()["id"]

        upload_response = client.post(
            f"/api/feedback/{feedback_id}/media",
            data={"media_type": "screenshot"},
            files={"file": ("test.png", b"test data", "image/png")},
        )
        media_id = upload_response.json()["id"]

        response = client.delete(f"/api/feedback/{feedback_id}/media/{media_id}")
        assert response.status_code == 204

        # Verify deleted
        get_response = client.get(f"/api/feedback/{feedback_id}/media/{media_id}")
        assert get_response.status_code == 404


class TestStatsAPI:
    """Tests for stats API endpoints."""

    def test_get_stats_empty(self, client: TestClient) -> None:
        """Test stats when empty."""
        response = client.get("/api/feedback/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0

    def test_get_stats_with_feedback(
        self, client: TestClient, sample_feedback_data: dict
    ) -> None:
        """Test stats with feedback."""
        client.post("/api/feedback", json=sample_feedback_data)
        client.post("/api/feedback", json=sample_feedback_data)

        response = client.get("/api/feedback/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["by_status"]["open"] == 2
        assert data["by_type"]["bug"] == 2
