"""Integration test: webhook health tracker + poller mode switching.

Verifies that the WebhookHealthTracker correctly drives PollerState mode
transitions and that the poller adapts its interval accordingly.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from syn_api.services.github_event_poller import GitHubEventPoller
from syn_api.services.webhook_health_tracker import WebhookHealthTracker
from syn_domain.contexts.github._shared.trigger_query_store import InMemoryTriggerQueryStore
from syn_domain.contexts.github.domain.aggregate_trigger.TriggerConfig import TriggerConfig
from syn_domain.contexts.github.slices.event_pipeline.pipeline import EventPipeline
from syn_domain.contexts.github.slices.event_pipeline.poller_state import PollerMode


class InMemoryDedup:
    def __init__(self) -> None:
        self._seen: set[str] = set()

    async def is_duplicate(self, dedup_key: str) -> bool:
        if dedup_key in self._seen:
            return True
        self._seen.add(dedup_key)
        return False

    async def mark_seen(self, dedup_key: str) -> None:
        self._seen.add(dedup_key)


class NullRepository:
    async def get_by_id(self, aggregate_id: str) -> None:
        return None

    async def save(self, aggregate: object) -> None:
        pass


class MockEventsClient:
    """Mock Events API client that tracks calls."""

    def __init__(self, poll_interval: int = 0) -> None:
        from syn_adapters.github.events_api_client import EventsAPIResponse

        self._response = EventsAPIResponse(
            events=[], poll_interval=poll_interval, has_new_events=False
        )
        self.poll_count = 0

    async def poll_repo_events(self, owner: str, repo: str, installation_id: str) -> Any:
        self.poll_count += 1
        return self._response


class MockPollingSettings:
    poll_interval_seconds: float = 0.05
    safety_net_interval_seconds: float = 0.1
    webhook_stale_threshold_seconds: float = 1800.0
    dedup_ttl_seconds: int = 86400
    disabled: bool = False
    enabled: bool = True


async def _setup_trigger(store: InMemoryTriggerQueryStore) -> None:
    await store.index_trigger(
        trigger_id="tr-001",
        name="test",
        event="push",
        repository="owner/repo",
        workflow_id="wf-001",
        conditions=[],
        input_mapping={},
        config=TriggerConfig(),
        installation_id="inst-1",
        created_by="test",
        status="active",
    )


@pytest.mark.asyncio
class TestWebhookHealthTrackerBehavior:
    """Unit-level tests for WebhookHealthTracker."""

    async def test_is_stale_when_never_received(self) -> None:
        tracker = WebhookHealthTracker()
        assert tracker.is_stale is True

    async def test_not_stale_after_record_received(self) -> None:
        tracker = WebhookHealthTracker(stale_threshold=1800.0)
        tracker.record_received()
        assert tracker.is_stale is False

    async def test_becomes_stale_after_threshold(self) -> None:
        tracker = WebhookHealthTracker(stale_threshold=0.05)
        tracker.record_received()
        assert tracker.is_stale is False
        await asyncio.sleep(0.06)
        assert tracker.is_stale is True

    async def test_seconds_since_last_none_when_never_received(self) -> None:
        tracker = WebhookHealthTracker()
        assert tracker.seconds_since_last is None

    async def test_seconds_since_last_updates(self) -> None:
        tracker = WebhookHealthTracker()
        tracker.record_received()
        await asyncio.sleep(0.05)
        elapsed = tracker.seconds_since_last
        assert elapsed is not None
        assert elapsed >= 0.04


@pytest.mark.asyncio
class TestPollerModeTransitions:
    """Verify poller adapts mode based on webhook health."""

    async def test_starts_in_active_polling_when_no_webhooks(self) -> None:
        """With no webhook received, poller should be in ACTIVE_POLLING mode."""
        tracker = WebhookHealthTracker()  # Never received → stale
        store = InMemoryTriggerQueryStore()
        await _setup_trigger(store)

        poller = GitHubEventPoller(
            events_client=MockEventsClient(),
            pipeline=EventPipeline(
                dedup=InMemoryDedup(), trigger_store=store, trigger_repo=NullRepository()
            ),
            health_tracker=tracker,
            trigger_store=store,
            settings=MockPollingSettings(),  # type: ignore[arg-type]
        )

        await poller.start()
        await asyncio.sleep(0.08)
        assert poller._state.mode == PollerMode.ACTIVE_POLLING
        await poller.stop()

    async def test_switches_to_safety_net_when_webhooks_healthy(self) -> None:
        """After webhook is received, poller should switch to SAFETY_NET mode."""
        tracker = WebhookHealthTracker(stale_threshold=1800.0)
        tracker.record_received()  # Mark webhooks as healthy
        store = InMemoryTriggerQueryStore()
        await _setup_trigger(store)

        poller = GitHubEventPoller(
            events_client=MockEventsClient(),
            pipeline=EventPipeline(
                dedup=InMemoryDedup(), trigger_store=store, trigger_repo=NullRepository()
            ),
            health_tracker=tracker,
            trigger_store=store,
            settings=MockPollingSettings(),  # type: ignore[arg-type]
        )

        await poller.start()
        await asyncio.sleep(0.08)
        assert poller._state.mode == PollerMode.SAFETY_NET
        await poller.stop()

    async def test_returns_to_active_polling_when_webhooks_go_stale(self) -> None:
        """When webhooks stop arriving, poller should switch back to ACTIVE_POLLING."""
        # Very short stale threshold for testing
        tracker = WebhookHealthTracker(stale_threshold=0.05)
        tracker.record_received()
        store = InMemoryTriggerQueryStore()
        await _setup_trigger(store)

        poller = GitHubEventPoller(
            events_client=MockEventsClient(poll_interval=0),
            pipeline=EventPipeline(
                dedup=InMemoryDedup(), trigger_store=store, trigger_repo=NullRepository()
            ),
            health_tracker=tracker,
            trigger_store=store,
            settings=MockPollingSettings(),  # type: ignore[arg-type]
        )

        await poller.start()
        # Initially healthy → SAFETY_NET
        await asyncio.sleep(0.03)
        assert poller._state.mode == PollerMode.SAFETY_NET

        # Wait for stale threshold to pass + a couple poll cycles
        await asyncio.sleep(0.15)
        assert poller._state.mode == PollerMode.ACTIVE_POLLING
        await poller.stop()

    async def test_safety_net_uses_longer_interval(self) -> None:
        """SAFETY_NET mode should use the larger safety_net_interval."""
        tracker = WebhookHealthTracker(stale_threshold=1800.0)
        tracker.record_received()
        store = InMemoryTriggerQueryStore()
        await _setup_trigger(store)

        mock_client = MockEventsClient()
        poller = GitHubEventPoller(
            events_client=mock_client,
            pipeline=EventPipeline(
                dedup=InMemoryDedup(), trigger_store=store, trigger_repo=NullRepository()
            ),
            health_tracker=tracker,
            trigger_store=store,
            settings=MockPollingSettings(),  # type: ignore[arg-type]
        )

        await poller.start()
        # Let it run a couple cycles in SAFETY_NET mode
        await asyncio.sleep(0.25)
        await poller.stop()

        # SAFETY_NET interval is 0.1s, so in 0.25s we expect ~2-3 polls
        # In ACTIVE_POLLING (0.05s interval) we'd expect ~5 polls
        assert mock_client.poll_count <= 4


@pytest.mark.asyncio
class TestPollerErrorBackoff:
    """Verify poller backs off on errors."""

    async def test_error_increases_backoff(self) -> None:
        """Errors should increase the poll interval via exponential backoff."""
        store = InMemoryTriggerQueryStore()
        await _setup_trigger(store)

        error_client = MockEventsClient()
        error_client.poll_repo_events = _make_failing_poll()  # type: ignore[assignment]

        tracker = WebhookHealthTracker()
        poller = GitHubEventPoller(
            events_client=error_client,  # type: ignore[arg-type]
            pipeline=EventPipeline(
                dedup=InMemoryDedup(), trigger_store=store, trigger_repo=NullRepository()
            ),
            health_tracker=tracker,
            trigger_store=store,
            settings=MockPollingSettings(),  # type: ignore[arg-type]
        )

        await poller.start()
        await asyncio.sleep(0.15)
        assert poller._state.consecutive_errors >= 1
        await poller.stop()

    async def test_success_resets_backoff(self) -> None:
        """A successful poll should reset the error counter."""
        store = InMemoryTriggerQueryStore()
        await _setup_trigger(store)

        tracker = WebhookHealthTracker()
        mock_client = MockEventsClient()

        poller = GitHubEventPoller(
            events_client=mock_client,
            pipeline=EventPipeline(
                dedup=InMemoryDedup(), trigger_store=store, trigger_repo=NullRepository()
            ),
            health_tracker=tracker,
            trigger_store=store,
            settings=MockPollingSettings(),  # type: ignore[arg-type]
        )

        # Manually set some errors
        poller._state.consecutive_errors = 3

        await poller.start()
        await asyncio.sleep(0.08)
        # Successful poll should have reset errors
        assert poller._state.consecutive_errors == 0
        await poller.stop()


def _make_failing_poll():
    """Create an async function that always raises."""

    async def _failing_poll(owner: str, repo: str, installation_id: str) -> None:
        msg = "Simulated API error"
        raise RuntimeError(msg)

    return _failing_poll
