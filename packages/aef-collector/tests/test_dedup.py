"""Tests for deduplication filter."""

import pytest

from aef_collector.collector.dedup import DeduplicationFilter


@pytest.mark.unit
class TestDeduplicationFilter:
    """Tests for the deduplication filter."""

    def test_is_duplicate_returns_false_first_time(self) -> None:
        """First check should return False."""
        dedup = DeduplicationFilter()

        result = dedup.is_duplicate("event-001")

        assert result is False

    def test_is_duplicate_returns_true_second_time(self) -> None:
        """Second check should return True."""
        dedup = DeduplicationFilter()

        dedup.is_duplicate("event-001")
        result = dedup.is_duplicate("event-001")

        assert result is True

    def test_different_events_not_duplicates(self) -> None:
        """Different events should not be duplicates."""
        dedup = DeduplicationFilter()

        result1 = dedup.is_duplicate("event-001")
        result2 = dedup.is_duplicate("event-002")

        assert result1 is False
        assert result2 is False

    def test_mark_seen_marks_event(self) -> None:
        """mark_seen should mark event as seen."""
        dedup = DeduplicationFilter()

        dedup.mark_seen("event-001")
        result = dedup.is_duplicate("event-001")

        assert result is True

    def test_is_seen_without_marking(self) -> None:
        """is_seen should not mark the event."""
        dedup = DeduplicationFilter()

        dedup.mark_seen("event-001")

        assert dedup.is_seen("event-001") is True
        assert dedup.is_seen("event-002") is False

    def test_size_property(self) -> None:
        """size should return number of tracked events."""
        dedup = DeduplicationFilter()

        dedup.is_duplicate("event-001")
        dedup.is_duplicate("event-002")
        dedup.is_duplicate("event-003")

        assert dedup.size == 3

    def test_clear_removes_all(self) -> None:
        """clear should remove all tracked events."""
        dedup = DeduplicationFilter()

        dedup.is_duplicate("event-001")
        dedup.is_duplicate("event-002")
        dedup.clear()

        assert dedup.size == 0
        assert dedup.is_duplicate("event-001") is False

    def test_eviction_on_max_size(self) -> None:
        """Oldest events should be evicted when max size reached."""
        dedup = DeduplicationFilter(max_size=3)

        dedup.is_duplicate("event-001")
        dedup.is_duplicate("event-002")
        dedup.is_duplicate("event-003")
        dedup.is_duplicate("event-004")  # Should evict event-001

        assert dedup.size == 3
        assert dedup.is_seen("event-001") is False  # Evicted
        assert dedup.is_seen("event-004") is True  # Present

    def test_stats_tracking(self) -> None:
        """Stats should track checks, hits, evictions."""
        dedup = DeduplicationFilter(max_size=2)

        dedup.is_duplicate("event-001")
        dedup.is_duplicate("event-001")  # Hit
        dedup.is_duplicate("event-002")
        dedup.is_duplicate("event-003")  # Eviction

        stats = dedup.stats
        assert stats["checks"] == 4
        assert stats["hits"] == 1
        assert stats["evictions"] == 1

    def test_hit_rate_calculation(self) -> None:
        """hit_rate should calculate percentage correctly."""
        dedup = DeduplicationFilter()

        dedup.is_duplicate("event-001")
        dedup.is_duplicate("event-001")  # Hit
        dedup.is_duplicate("event-002")
        dedup.is_duplicate("event-001")  # Hit

        # 2 hits out of 4 checks = 50%
        assert dedup.hit_rate() == 50.0

    def test_hit_rate_empty(self) -> None:
        """hit_rate should return 0 when no checks."""
        dedup = DeduplicationFilter()

        assert dedup.hit_rate() == 0.0
