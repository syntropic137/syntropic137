"""Tests for GitHubEventPoller background task."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from syn_api.services.github_event_poller import GitHubEventPoller
from syn_api.services.webhook_health_tracker import WebhookHealthTracker
from syn_domain.contexts.github._shared.trigger_query_store import InMemoryTriggerQueryStore
from syn_domain.contexts.github.domain.aggregate_trigger.TriggerConfig import TriggerConfig
from syn_domain.contexts.github.slices.event_pipeline.pipeline import EventPipeline


class MockEventsClient:
    """Mock GitHub Events API client for testing."""

    def __init__(self, events: list[dict[str, Any]] | None = None) -> None:
        from syn_adapters.github.events_api_client import EventsAPIResponse

        self._response = EventsAPIResponse(
            events=events or [],
            poll_interval=60,
            has_new_events=bool(events),
        )
        self.poll_count = 0

    async def poll_repo_events(self, owner: str, repo: str, installation_id: str) -> Any:
        self.poll_count += 1
        return self._response


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


class MockPollingSettings:
    """Minimal mock matching PollingSettings interface."""

    poll_interval_seconds: float = 0.05  # Very fast for tests
    safety_net_interval_seconds: float = 0.1
    webhook_stale_threshold_seconds: float = 1800.0
    dedup_ttl_seconds: int = 86400
    disabled: bool = False
    enabled: bool = True


async def _index_trigger(store: InMemoryTriggerQueryStore) -> None:
    await store.index_trigger(
        trigger_id="tr-001",
        name="test-trigger",
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


class TestPollerStartStop:
    @pytest.mark.asyncio
    async def test_starts_and_stops_cleanly(self) -> None:
        store = InMemoryTriggerQueryStore()
        poller = GitHubEventPoller(
            events_client=MockEventsClient(),
            pipeline=EventPipeline(
                dedup=InMemoryDedup(),
                trigger_store=store,
                trigger_repo=NullRepository(),
            ),
            health_tracker=WebhookHealthTracker(),
            trigger_store=store,
            settings=MockPollingSettings(),  # type: ignore[arg-type]
        )

        await poller.start()
        assert poller.is_running

        await poller.stop()
        assert not poller.is_running

    @pytest.mark.asyncio
    async def test_polls_repos_with_active_triggers(self) -> None:
        store = InMemoryTriggerQueryStore()
        await _index_trigger(store)

        mock_client = MockEventsClient()
        poller = GitHubEventPoller(
            events_client=mock_client,
            pipeline=EventPipeline(
                dedup=InMemoryDedup(),
                trigger_store=store,
                trigger_repo=NullRepository(),
            ),
            health_tracker=WebhookHealthTracker(),
            trigger_store=store,
            settings=MockPollingSettings(),  # type: ignore[arg-type]
        )

        await poller.start()
        # Let it run a couple cycles
        await asyncio.sleep(0.15)
        await poller.stop()

        assert mock_client.poll_count >= 1

    @pytest.mark.asyncio
    async def test_no_api_calls_without_triggers(self) -> None:
        store = InMemoryTriggerQueryStore()  # empty — no triggers
        mock_client = MockEventsClient()

        poller = GitHubEventPoller(
            events_client=mock_client,
            pipeline=EventPipeline(
                dedup=InMemoryDedup(),
                trigger_store=store,
                trigger_repo=NullRepository(),
            ),
            health_tracker=WebhookHealthTracker(),
            trigger_store=store,
            settings=MockPollingSettings(),  # type: ignore[arg-type]
        )

        await poller.start()
        await asyncio.sleep(0.15)
        await poller.stop()

        assert mock_client.poll_count == 0

    @pytest.mark.asyncio
    async def test_processes_polled_events(self) -> None:
        store = InMemoryTriggerQueryStore()
        await _index_trigger(store)

        events = [
            {
                "id": "12345",
                "type": "PushEvent",
                "repo": {"name": "owner/repo"},
                "payload": {"after": "abc123"},
                "created_at": "2026-01-01T00:00:00Z",
            }
        ]

        dedup = InMemoryDedup()
        poller = GitHubEventPoller(
            events_client=MockEventsClient(events=events),
            pipeline=EventPipeline(
                dedup=dedup,
                trigger_store=store,
                trigger_repo=NullRepository(),
            ),
            health_tracker=WebhookHealthTracker(),
            trigger_store=store,
            settings=MockPollingSettings(),  # type: ignore[arg-type]
        )

        await poller.start()
        await asyncio.sleep(0.15)
        await poller.stop()

        # The event's dedup key should have been recorded
        assert len(dedup._seen) >= 1
