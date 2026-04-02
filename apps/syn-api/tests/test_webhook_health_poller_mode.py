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


class FakeClock:
    """Deterministic clock for testing time-dependent behavior."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


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
    poll_interval_seconds: float = 60.0
    safety_net_interval_seconds: float = 300.0
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


async def _instant_sleep(_seconds: float) -> None:
    """No-op sleep for fast tests."""
    await asyncio.sleep(0)


async def _wait_for_poll_count(client: MockEventsClient, count: int, timeout: float = 2.0) -> None:
    """Wait until the mock client has been polled at least ``count`` times."""
    deadline = asyncio.get_event_loop().time() + timeout
    while client.poll_count < count:
        if asyncio.get_event_loop().time() > deadline:
            msg = f"Timed out waiting for poll_count >= {count} (got {client.poll_count})"
            raise TimeoutError(msg)
        await asyncio.sleep(0)


@pytest.mark.asyncio
class TestWebhookHealthTrackerBehavior:
    """Unit-level tests for WebhookHealthTracker."""

    async def test_is_stale_when_never_received(self) -> None:
        tracker = WebhookHealthTracker()
        assert tracker.is_stale is True

    async def test_not_stale_after_record_received(self) -> None:
        clock = FakeClock(start=1000.0)
        tracker = WebhookHealthTracker(stale_threshold=1800.0, clock=clock)
        tracker.record_received()
        assert tracker.is_stale is False

    async def test_becomes_stale_after_threshold(self) -> None:
        clock = FakeClock(start=1000.0)
        tracker = WebhookHealthTracker(stale_threshold=60.0, clock=clock)
        tracker.record_received()
        assert tracker.is_stale is False
        clock.advance(61.0)
        assert tracker.is_stale is True

    async def test_seconds_since_last_none_when_never_received(self) -> None:
        tracker = WebhookHealthTracker()
        assert tracker.seconds_since_last is None

    async def test_seconds_since_last_updates(self) -> None:
        clock = FakeClock(start=1000.0)
        tracker = WebhookHealthTracker(clock=clock)
        tracker.record_received()
        clock.advance(50.0)
        elapsed = tracker.seconds_since_last
        assert elapsed is not None
        assert elapsed == pytest.approx(50.0)


@pytest.mark.asyncio
class TestPollerModeTransitions:
    """Verify poller adapts mode based on webhook health."""

    async def test_starts_in_active_polling_when_no_webhooks(self) -> None:
        """With no webhook received, poller should be in ACTIVE_POLLING mode."""
        clock = FakeClock(start=1000.0)
        tracker = WebhookHealthTracker(clock=clock)  # Never received -> stale
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
            sleep=_instant_sleep,
        )

        await poller.start()
        await _wait_for_poll_count(mock_client, 1)
        assert poller._state.mode == PollerMode.ACTIVE_POLLING
        await poller.stop()

    async def test_switches_to_safety_net_when_webhooks_healthy(self) -> None:
        """After webhook is received, poller should switch to SAFETY_NET mode."""
        clock = FakeClock(start=1000.0)
        tracker = WebhookHealthTracker(stale_threshold=1800.0, clock=clock)
        tracker.record_received()  # Mark webhooks as healthy
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
            sleep=_instant_sleep,
        )

        await poller.start()
        await _wait_for_poll_count(mock_client, 1)
        assert poller._state.mode == PollerMode.SAFETY_NET
        await poller.stop()

    async def test_returns_to_active_polling_when_webhooks_go_stale(self) -> None:
        """When webhooks stop arriving, poller should switch back to ACTIVE_POLLING."""
        clock = FakeClock(start=1000.0)
        tracker = WebhookHealthTracker(stale_threshold=1800.0, clock=clock)
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
            sleep=_instant_sleep,
        )

        await poller.start()
        # Initially healthy -> SAFETY_NET
        await _wait_for_poll_count(mock_client, 1)
        assert poller._state.mode == PollerMode.SAFETY_NET

        # Advance clock past stale threshold
        clock.advance(1801.0)
        initial_count = mock_client.poll_count
        await _wait_for_poll_count(mock_client, initial_count + 1)
        assert poller._state.mode == PollerMode.ACTIVE_POLLING
        await poller.stop()

    async def test_safety_net_uses_longer_interval(self) -> None:
        """SAFETY_NET mode should use the larger safety_net_interval."""
        clock = FakeClock(start=1000.0)
        tracker = WebhookHealthTracker(stale_threshold=1800.0, clock=clock)
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
            sleep=_instant_sleep,
        )

        await poller.start()
        await _wait_for_poll_count(mock_client, 1)
        # In SAFETY_NET mode, the interval should be the safety_net value (300s)
        assert poller._state.mode == PollerMode.SAFETY_NET
        assert poller._state.current_interval == 300.0
        await poller.stop()


@pytest.mark.asyncio
class TestPollerErrorBackoff:
    """Verify poller backs off on errors."""

    async def test_error_increases_backoff(self) -> None:
        """Errors should increase the poll interval via exponential backoff."""
        store = InMemoryTriggerQueryStore()
        await _setup_trigger(store)

        error_client = MockEventsClient()
        error_client.poll_repo_events = _make_failing_poll()  # type: ignore[assignment]

        clock = FakeClock(start=1000.0)
        tracker = WebhookHealthTracker(clock=clock)
        poller = GitHubEventPoller(
            events_client=error_client,  # type: ignore[arg-type]
            pipeline=EventPipeline(
                dedup=InMemoryDedup(), trigger_store=store, trigger_repo=NullRepository()
            ),
            health_tracker=tracker,
            trigger_store=store,
            settings=MockPollingSettings(),  # type: ignore[arg-type]
            sleep=_instant_sleep,
        )

        await poller.start()
        # Wait for at least one poll cycle (the failing poll increments poll_count
        # on the error_client, but we can't wait on that since it's overridden).
        # Instead wait for the consecutive_errors to be set.
        deadline = asyncio.get_event_loop().time() + 2.0
        while poller._state.consecutive_errors < 1:
            if asyncio.get_event_loop().time() > deadline:
                msg = "Timed out waiting for errors"
                raise TimeoutError(msg)
            await asyncio.sleep(0)
        assert poller._state.consecutive_errors >= 1
        await poller.stop()

    async def test_success_resets_backoff(self) -> None:
        """A successful poll should reset the error counter."""
        store = InMemoryTriggerQueryStore()
        await _setup_trigger(store)

        clock = FakeClock(start=1000.0)
        tracker = WebhookHealthTracker(clock=clock)
        mock_client = MockEventsClient()

        poller = GitHubEventPoller(
            events_client=mock_client,
            pipeline=EventPipeline(
                dedup=InMemoryDedup(), trigger_store=store, trigger_repo=NullRepository()
            ),
            health_tracker=tracker,
            trigger_store=store,
            settings=MockPollingSettings(),  # type: ignore[arg-type]
            sleep=_instant_sleep,
        )

        # Manually set some errors
        poller._state.consecutive_errors = 3

        await poller.start()
        await _wait_for_poll_count(mock_client, 1)
        # Successful poll should have reset errors
        assert poller._state.consecutive_errors == 0
        await poller.stop()


def _make_failing_poll():
    """Create an async function that always raises."""

    async def _failing_poll(owner: str, repo: str, installation_id: str) -> None:
        msg = "Simulated API error"
        raise RuntimeError(msg)

    return _failing_poll
