"""Tests for storage implementations."""

import pytest

from ui_feedback.models import FeedbackCreate, FeedbackType, FeedbackUpdate, Priority, Status
from ui_feedback.storage.memory import InMemoryFeedbackStorage


@pytest.fixture
def storage() -> InMemoryFeedbackStorage:
    """Create a fresh in-memory storage for each test."""
    return InMemoryFeedbackStorage()


@pytest.fixture
def sample_feedback() -> FeedbackCreate:
    """Sample feedback data for testing."""
    return FeedbackCreate(
        url="http://localhost:3000/dashboard",
        route="/dashboard",
        viewport_width=1920,
        viewport_height=1080,
        click_x=500,
        click_y=300,
        css_selector="div.card > button",
        xpath="/html/body/div[1]/button",
        component_name="DashboardCard",
        feedback_type=FeedbackType.BUG,
        comment="Button doesn't work on click",
        priority=Priority.HIGH,
        app_name="test-app",
        app_version="1.0.0",
        user_agent="Mozilla/5.0",
    )


class TestFeedbackCRUD:
    """Tests for feedback CRUD operations."""

    async def test_create_feedback(
        self, storage: InMemoryFeedbackStorage, sample_feedback: FeedbackCreate
    ) -> None:
        """Test creating a feedback item."""
        item = await storage.create_feedback(sample_feedback)

        assert item.id is not None
        assert item.url == sample_feedback.url
        assert item.comment == sample_feedback.comment
        assert item.status == Status.OPEN
        assert item.priority == Priority.HIGH
        assert item.app_name == sample_feedback.app_name
        assert item.media_count == 0

    async def test_get_feedback(
        self, storage: InMemoryFeedbackStorage, sample_feedback: FeedbackCreate
    ) -> None:
        """Test retrieving a feedback item."""
        created = await storage.create_feedback(sample_feedback)
        retrieved = await storage.get_feedback(created.id)

        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.url == created.url
        assert retrieved.media == []

    async def test_get_feedback_not_found(self, storage: InMemoryFeedbackStorage) -> None:
        """Test retrieving non-existent feedback."""
        from uuid import uuid4

        result = await storage.get_feedback(uuid4())
        assert result is None

    async def test_list_feedback_empty(self, storage: InMemoryFeedbackStorage) -> None:
        """Test listing feedback when empty."""
        items, total = await storage.list_feedback()
        assert items == []
        assert total == 0

    async def test_list_feedback_with_items(
        self, storage: InMemoryFeedbackStorage, sample_feedback: FeedbackCreate
    ) -> None:
        """Test listing feedback with items."""
        await storage.create_feedback(sample_feedback)
        await storage.create_feedback(sample_feedback)

        items, total = await storage.list_feedback()
        assert len(items) == 2
        assert total == 2

    async def test_list_feedback_filter_by_status(
        self, storage: InMemoryFeedbackStorage, sample_feedback: FeedbackCreate
    ) -> None:
        """Test filtering feedback by status."""
        item1 = await storage.create_feedback(sample_feedback)
        await storage.create_feedback(sample_feedback)

        # Update one to resolved
        await storage.update_feedback(item1.id, FeedbackUpdate(status=Status.RESOLVED))

        items, total = await storage.list_feedback(status="resolved")
        assert len(items) == 1
        assert total == 1
        assert items[0].id == item1.id

    async def test_list_feedback_filter_by_type(
        self, storage: InMemoryFeedbackStorage, sample_feedback: FeedbackCreate
    ) -> None:
        """Test filtering feedback by type."""
        await storage.create_feedback(sample_feedback)

        # Create another with different type
        other = sample_feedback.model_copy(update={"feedback_type": FeedbackType.FEATURE})
        await storage.create_feedback(other)

        items, total = await storage.list_feedback(feedback_type="bug")
        assert len(items) == 1
        assert total == 1

    async def test_list_feedback_search(
        self, storage: InMemoryFeedbackStorage, sample_feedback: FeedbackCreate
    ) -> None:
        """Test searching feedback by comment."""
        await storage.create_feedback(sample_feedback)

        other = sample_feedback.model_copy(update={"comment": "Different issue here"})
        await storage.create_feedback(other)

        items, total = await storage.list_feedback(search="button")
        assert len(items) == 1
        assert total == 1
        assert "Button" in items[0].comment

    async def test_list_feedback_pagination(
        self, storage: InMemoryFeedbackStorage, sample_feedback: FeedbackCreate
    ) -> None:
        """Test pagination of feedback list."""
        for _ in range(5):
            await storage.create_feedback(sample_feedback)

        items, total = await storage.list_feedback(page=1, page_size=2)
        assert len(items) == 2
        assert total == 5

        items, total = await storage.list_feedback(page=3, page_size=2)
        assert len(items) == 1
        assert total == 5

    async def test_update_feedback(
        self, storage: InMemoryFeedbackStorage, sample_feedback: FeedbackCreate
    ) -> None:
        """Test updating a feedback item."""
        created = await storage.create_feedback(sample_feedback)

        updated = await storage.update_feedback(
            created.id,
            FeedbackUpdate(
                status=Status.IN_PROGRESS,
                assigned_to="developer@example.com",
            ),
        )

        assert updated is not None
        assert updated.status == Status.IN_PROGRESS
        assert updated.assigned_to == "developer@example.com"

    async def test_update_feedback_resolved_sets_timestamp(
        self, storage: InMemoryFeedbackStorage, sample_feedback: FeedbackCreate
    ) -> None:
        """Test that resolving feedback sets resolved_at."""
        created = await storage.create_feedback(sample_feedback)
        assert created.resolved_at is None

        updated = await storage.update_feedback(
            created.id,
            FeedbackUpdate(status=Status.RESOLVED, resolution_notes="Fixed in PR #123"),
        )

        assert updated is not None
        assert updated.status == Status.RESOLVED
        assert updated.resolved_at is not None
        assert updated.resolution_notes == "Fixed in PR #123"

    async def test_delete_feedback(
        self, storage: InMemoryFeedbackStorage, sample_feedback: FeedbackCreate
    ) -> None:
        """Test deleting a feedback item."""
        created = await storage.create_feedback(sample_feedback)
        deleted = await storage.delete_feedback(created.id)

        assert deleted is True
        assert await storage.get_feedback(created.id) is None

    async def test_delete_feedback_not_found(self, storage: InMemoryFeedbackStorage) -> None:
        """Test deleting non-existent feedback."""
        from uuid import uuid4

        deleted = await storage.delete_feedback(uuid4())
        assert deleted is False


class TestMediaCRUD:
    """Tests for media CRUD operations."""

    async def test_create_media(
        self, storage: InMemoryFeedbackStorage, sample_feedback: FeedbackCreate
    ) -> None:
        """Test creating a media attachment."""
        feedback = await storage.create_feedback(sample_feedback)

        media = await storage.create_media(
            feedback_id=feedback.id,
            media_type="screenshot",
            mime_type="image/png",
            data=b"fake image data",
            file_name="screenshot.png",
        )

        assert media.id is not None
        assert media.feedback_id == feedback.id
        assert media.media_type == "screenshot"
        assert media.file_size == len(b"fake image data")

    async def test_get_media(
        self, storage: InMemoryFeedbackStorage, sample_feedback: FeedbackCreate
    ) -> None:
        """Test retrieving media with data."""
        feedback = await storage.create_feedback(sample_feedback)
        created = await storage.create_media(
            feedback_id=feedback.id,
            media_type="voice_note",
            mime_type="audio/webm",
            data=b"fake audio data",
        )

        result = await storage.get_media(created.id)
        assert result is not None
        item, data = result
        assert item.id == created.id
        assert data == b"fake audio data"

    async def test_delete_media(
        self, storage: InMemoryFeedbackStorage, sample_feedback: FeedbackCreate
    ) -> None:
        """Test deleting media."""
        feedback = await storage.create_feedback(sample_feedback)
        media = await storage.create_media(
            feedback_id=feedback.id,
            media_type="screenshot",
            mime_type="image/png",
            data=b"fake data",
        )

        deleted = await storage.delete_media(media.id)
        assert deleted is True
        assert await storage.get_media(media.id) is None

    async def test_feedback_with_media_count(
        self, storage: InMemoryFeedbackStorage, sample_feedback: FeedbackCreate
    ) -> None:
        """Test that feedback includes correct media count."""
        feedback = await storage.create_feedback(sample_feedback)

        await storage.create_media(
            feedback_id=feedback.id,
            media_type="screenshot",
            mime_type="image/png",
            data=b"fake data 1",
        )
        await storage.create_media(
            feedback_id=feedback.id,
            media_type="voice_note",
            mime_type="audio/webm",
            data=b"fake data 2",
        )

        retrieved = await storage.get_feedback(feedback.id)
        assert retrieved is not None
        assert retrieved.media_count == 2
        assert len(retrieved.media) == 2

    async def test_delete_feedback_cascades_media(
        self, storage: InMemoryFeedbackStorage, sample_feedback: FeedbackCreate
    ) -> None:
        """Test that deleting feedback also deletes media."""
        feedback = await storage.create_feedback(sample_feedback)
        media = await storage.create_media(
            feedback_id=feedback.id,
            media_type="screenshot",
            mime_type="image/png",
            data=b"fake data",
        )

        await storage.delete_feedback(feedback.id)
        assert await storage.get_media(media.id) is None


class TestStats:
    """Tests for statistics."""

    async def test_stats_empty(self, storage: InMemoryFeedbackStorage) -> None:
        """Test stats when no feedback exists."""
        stats = await storage.get_stats()
        assert stats.total == 0

    async def test_stats_with_feedback(
        self, storage: InMemoryFeedbackStorage, sample_feedback: FeedbackCreate
    ) -> None:
        """Test stats with feedback items."""
        await storage.create_feedback(sample_feedback)
        await storage.create_feedback(sample_feedback)

        feature_feedback = sample_feedback.model_copy(
            update={"feedback_type": FeedbackType.FEATURE}
        )
        await storage.create_feedback(feature_feedback)

        stats = await storage.get_stats()

        assert stats.total == 3
        assert stats.by_status.open == 3
        assert stats.by_type.bug == 2
        assert stats.by_type.feature == 1
        assert stats.by_app["test-app"] == 3

    async def test_stats_filter_by_app(
        self, storage: InMemoryFeedbackStorage, sample_feedback: FeedbackCreate
    ) -> None:
        """Test stats filtered by app."""
        await storage.create_feedback(sample_feedback)

        other_app = sample_feedback.model_copy(update={"app_name": "other-app"})
        await storage.create_feedback(other_app)

        stats = await storage.get_stats(app_name="test-app")

        assert stats.total == 1
        assert stats.by_app == {}  # Empty when filtering by specific app
