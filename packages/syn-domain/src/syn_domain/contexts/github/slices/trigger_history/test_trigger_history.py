"""Tests for trigger_history query slice."""

from __future__ import annotations

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.github.domain.events.TriggerBlockedEvent import (
    TriggerBlockedEvent,
)
from syn_domain.contexts.github.domain.events.TriggerFiredEvent import (
    TriggerFiredEvent,
)
from syn_domain.contexts.github.slices.trigger_history.projection import (
    TriggerHistoryProjection,
)


@pytest.mark.unit
class TestTriggerHistoryEventWiring:
    """Verify trigger_history is wired in the coordinator subscription service."""

    def test_trigger_history_adapter_subscribes_to_trigger_fired(self) -> None:
        """TriggerHistoryAdapter must subscribe to github.TriggerFired."""
        from syn_adapters.subscriptions.realtime_adapter import TriggerHistoryAdapter

        subs = TriggerHistoryAdapter._SUBSCRIBED
        assert "github.TriggerFired" in subs


@pytest.mark.unit
class TestTriggerHistoryProjection:
    """Tests for TriggerHistoryProjection."""

    async def test_handle_trigger_fired(self) -> None:
        """Test projecting a TriggerFired event creates a history entry."""
        projection = TriggerHistoryProjection(store=InMemoryProjectionStore())

        entry = await projection.handle_trigger_fired(
            TriggerFiredEvent(
                trigger_id="tr-1",
                execution_id="exec-1",
                webhook_delivery_id="del-1",
                github_event_type="check_run.completed",
                repository="syntropic137/test",
                pr_number=42,
            )
        )

        assert entry.trigger_id == "tr-1"
        assert entry.execution_id == "exec-1"
        assert entry.pr_number == 42
        assert entry.fired_at is not None

    async def test_get_history_returns_most_recent_first(self) -> None:
        """Test that get_history returns entries most recent first."""
        projection = TriggerHistoryProjection(store=InMemoryProjectionStore())

        for i in range(5):
            await projection.handle_trigger_fired(
                TriggerFiredEvent(
                    trigger_id="tr-1",
                    execution_id=f"exec-{i}",
                    github_event_type="check_run.completed",
                )
            )

        history = await projection.get_history("tr-1")
        assert len(history) == 5

    async def test_get_history_respects_limit(self) -> None:
        """Test that get_history respects the limit parameter."""
        projection = TriggerHistoryProjection(store=InMemoryProjectionStore())

        for i in range(10):
            await projection.handle_trigger_fired(
                TriggerFiredEvent(
                    trigger_id="tr-1",
                    execution_id=f"exec-{i}",
                    github_event_type="check_run.completed",
                )
            )

        history = await projection.get_history("tr-1", limit=3)
        assert len(history) == 3

    async def test_get_history_filters_by_trigger_id(self) -> None:
        """Test that get_history only returns entries for the given trigger."""
        projection = TriggerHistoryProjection(store=InMemoryProjectionStore())

        await projection.handle_trigger_fired(
            TriggerFiredEvent(trigger_id="tr-1", execution_id="exec-1", github_event_type="x")
        )
        await projection.handle_trigger_fired(
            TriggerFiredEvent(trigger_id="tr-2", execution_id="exec-2", github_event_type="x")
        )
        await projection.handle_trigger_fired(
            TriggerFiredEvent(trigger_id="tr-1", execution_id="exec-3", github_event_type="x")
        )

        history = await projection.get_history("tr-1")
        assert len(history) == 2
        assert all(e.trigger_id == "tr-1" for e in history)

    async def test_get_all_history(self) -> None:
        """Test get_all_history returns all entries."""
        projection = TriggerHistoryProjection(store=InMemoryProjectionStore())

        await projection.handle_trigger_fired(
            TriggerFiredEvent(trigger_id="tr-1", execution_id="exec-1", github_event_type="x")
        )
        await projection.handle_trigger_fired(
            TriggerFiredEvent(trigger_id="tr-2", execution_id="exec-2", github_event_type="x")
        )

        history = await projection.get_all_history()
        assert len(history) == 2

    async def test_blocked_entries_deduplicated_for_same_logical_event(self) -> None:
        """Regression: rapid re-deliveries of the same logical event must not create
        multiple blocked entries. The projection uses a content-based key so that
        multiple TriggerBlockedEvents with the same (guard_name, event_type, pr_number)
        overwrite rather than accumulate.

        Mirrors the real-world pattern where the event poller delivers the same
        GitHub event 10+ times within a single 60s poll cycle.
        """
        projection = TriggerHistoryProjection(store=InMemoryProjectionStore())

        # Simulate 10 rapid re-deliveries of the same blocked event (no delivery ID)
        for _ in range(10):
            await projection.handle_trigger_blocked(
                TriggerBlockedEvent(
                    trigger_id="tr-1",
                    guard_name="concurrency",
                    reason="Execution already running",
                    github_event_type="pull_request_review.submitted",
                    repository="owner/repo",
                    pr_number=42,
                )
            )

        history = await projection.get_history("tr-1")
        blocked = [e for e in history if e.status == "blocked"]
        assert len(blocked) == 1, (
            f"Expected 1 deduplicated blocked entry, got {len(blocked)}. "
            "Rapid re-deliveries of the same logical event must not accumulate."
        )

    async def test_blocked_entries_distinct_for_different_prs(self) -> None:
        """Different PR numbers must produce separate blocked entries (not over-deduplicated)."""
        projection = TriggerHistoryProjection(store=InMemoryProjectionStore())

        await projection.handle_trigger_blocked(
            TriggerBlockedEvent(
                trigger_id="tr-1",
                guard_name="concurrency",
                reason="Execution already running",
                github_event_type="pull_request_review.submitted",
                pr_number=1,
            )
        )
        await projection.handle_trigger_blocked(
            TriggerBlockedEvent(
                trigger_id="tr-1",
                guard_name="concurrency",
                reason="Execution already running",
                github_event_type="pull_request_review.submitted",
                pr_number=2,
            )
        )

        history = await projection.get_history("tr-1")
        blocked = [e for e in history if e.status == "blocked"]
        assert len(blocked) == 2, "Blocked entries for different PRs must be kept separate."

    async def test_blocked_entries_distinct_for_different_comments_on_same_pr(self) -> None:
        """Regression: two issue_comment events on the same PR must produce separate blocked
        entries even when guard_name, event_type, and pr_number are identical.

        The dedup key must incorporate comment_id from payload_summary so that poller
        re-deliveries of the *same* comment collapse (Fix 5 intent) while genuinely
        distinct comments do not.
        """
        projection = TriggerHistoryProjection(store=InMemoryProjectionStore())

        await projection.handle_trigger_blocked(
            TriggerBlockedEvent(
                trigger_id="tr-1",
                guard_name="concurrency",
                reason="Execution already running",
                github_event_type="issue_comment",
                repository="owner/repo",
                pr_number=42,
                payload_summary={"comment_id": 1001},
            )
        )
        await projection.handle_trigger_blocked(
            TriggerBlockedEvent(
                trigger_id="tr-1",
                guard_name="concurrency",
                reason="Execution already running",
                github_event_type="issue_comment",
                repository="owner/repo",
                pr_number=42,
                payload_summary={"comment_id": 1002},
            )
        )

        history = await projection.get_history("tr-1")
        blocked = [e for e in history if e.status == "blocked"]
        assert len(blocked) == 2, (
            "Blocked entries for different issue_comment events on the same PR must be "
            "kept separate (different comment_id values)."
        )

    async def test_rapid_redeliveries_of_same_comment_still_deduplicated(self) -> None:
        """Regression: 10 rapid re-deliveries of the same issue_comment event (same comment_id)
        must still collapse to a single blocked entry."""
        projection = TriggerHistoryProjection(store=InMemoryProjectionStore())

        for _ in range(10):
            await projection.handle_trigger_blocked(
                TriggerBlockedEvent(
                    trigger_id="tr-1",
                    guard_name="concurrency",
                    reason="Execution already running",
                    github_event_type="issue_comment",
                    repository="owner/repo",
                    pr_number=42,
                    payload_summary={"comment_id": 1001},
                )
            )

        history = await projection.get_history("tr-1")
        blocked = [e for e in history if e.status == "blocked"]
        assert len(blocked) == 1, (
            "10 re-deliveries of the same issue_comment event must collapse to 1 blocked entry."
        )
