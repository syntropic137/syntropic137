"""Integration test: cross-source deduplication — same logical event from webhook + poller.

Verifies that when both webhook and Events API deliver the same logical event
(e.g., a push with the same after SHA), only the first one triggers evaluation
and the second is deduplicated.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from syn_domain.contexts.github._shared.trigger_query_store import InMemoryTriggerQueryStore
from syn_domain.contexts.github.domain.aggregate_trigger.TriggerConfig import TriggerConfig
from syn_domain.contexts.github.slices.event_pipeline.dedup_keys import compute_dedup_key
from syn_domain.contexts.github.slices.event_pipeline.normalized_event import (
    EventSource,
    NormalizedEvent,
)
from syn_domain.contexts.github.slices.event_pipeline.pipeline import EventPipeline


class InMemoryDedup:
    """In-memory dedup for test isolation."""

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


async def _setup_trigger(store: InMemoryTriggerQueryStore) -> None:
    await store.index_trigger(
        trigger_id="tr-001",
        name="deploy-on-push",
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


def _make_push_payload(after_sha: str) -> dict[str, Any]:
    """Create a push payload that both webhook and Events API would produce."""
    return {
        "after": after_sha,
        "ref": "refs/heads/main",
        "repository": {"full_name": "owner/repo"},
    }


@pytest.mark.asyncio
class TestCrossSourceDedup:
    """Verify that the same logical event from two sources is deduplicated."""

    async def test_webhook_then_poller_deduplicates(self) -> None:
        """Webhook arrives first, then Events API delivers the same push → deduplicated."""
        dedup = InMemoryDedup()
        store = InMemoryTriggerQueryStore()
        await _setup_trigger(store)

        pipeline = EventPipeline(
            dedup=dedup,
            trigger_store=store,
            trigger_repo=NullRepository(),
        )

        payload = _make_push_payload("abc123def456")
        dedup_key = compute_dedup_key("push", "", payload)

        # Webhook event arrives first
        webhook_event = NormalizedEvent(
            event_type="push",
            action="",
            repository="owner/repo",
            installation_id="inst-1",
            dedup_key=dedup_key,
            source=EventSource.WEBHOOK,
            payload=payload,
            received_at=datetime.now(UTC),
            delivery_id="gh-delivery-123",
        )
        result1 = await pipeline.ingest(webhook_event)
        assert result1.status == "processed"

        # Same event from Events API
        poller_event = NormalizedEvent(
            event_type="push",
            action="",
            repository="owner/repo",
            installation_id="inst-1",
            dedup_key=dedup_key,  # Same content-based key
            source=EventSource.EVENTS_API,
            payload=payload,
            received_at=datetime.now(UTC),
            events_api_id="98765",
        )
        result2 = await pipeline.ingest(poller_event)
        assert result2.status == "deduplicated"

    async def test_poller_then_webhook_deduplicates(self) -> None:
        """Events API arrives first, then webhook delivers the same push → deduplicated."""
        dedup = InMemoryDedup()
        store = InMemoryTriggerQueryStore()
        await _setup_trigger(store)

        pipeline = EventPipeline(
            dedup=dedup,
            trigger_store=store,
            trigger_repo=NullRepository(),
        )

        payload = _make_push_payload("feed0000dead")
        dedup_key = compute_dedup_key("push", "", payload)

        # Poller event arrives first
        poller_event = NormalizedEvent(
            event_type="push",
            action="",
            repository="owner/repo",
            installation_id="inst-1",
            dedup_key=dedup_key,
            source=EventSource.EVENTS_API,
            payload=payload,
            received_at=datetime.now(UTC),
            events_api_id="11111",
        )
        result1 = await pipeline.ingest(poller_event)
        assert result1.status == "processed"

        # Same event from webhook
        webhook_event = NormalizedEvent(
            event_type="push",
            action="",
            repository="owner/repo",
            installation_id="inst-1",
            dedup_key=dedup_key,
            source=EventSource.WEBHOOK,
            payload=payload,
            received_at=datetime.now(UTC),
            delivery_id="gh-delivery-456",
        )
        result2 = await pipeline.ingest(webhook_event)
        assert result2.status == "deduplicated"

    async def test_different_events_are_not_deduplicated(self) -> None:
        """Two different pushes (different SHAs) both get processed."""
        dedup = InMemoryDedup()
        store = InMemoryTriggerQueryStore()
        await _setup_trigger(store)

        pipeline = EventPipeline(
            dedup=dedup,
            trigger_store=store,
            trigger_repo=NullRepository(),
        )

        payload_a = _make_push_payload("aaa111")
        payload_b = _make_push_payload("bbb222")

        event_a = NormalizedEvent(
            event_type="push",
            action="",
            repository="owner/repo",
            installation_id="inst-1",
            dedup_key=compute_dedup_key("push", "", payload_a),
            source=EventSource.WEBHOOK,
            payload=payload_a,
            received_at=datetime.now(UTC),
            delivery_id="d-1",
        )
        event_b = NormalizedEvent(
            event_type="push",
            action="",
            repository="owner/repo",
            installation_id="inst-1",
            dedup_key=compute_dedup_key("push", "", payload_b),
            source=EventSource.EVENTS_API,
            payload=payload_b,
            received_at=datetime.now(UTC),
            events_api_id="22222",
        )

        result_a = await pipeline.ingest(event_a)
        result_b = await pipeline.ingest(event_b)

        assert result_a.status == "processed"
        assert result_b.status == "processed"

    async def test_cross_source_dedup_key_consistency(self) -> None:
        """Verify that webhook and Events API payloads produce the same dedup key.

        The event_type_mapper enriches Events API payloads with
        ``repository.full_name`` so the dedup key is identical to the webhook path.
        """
        from syn_domain.contexts.github.slices.event_pipeline.event_type_mapper import (
            map_events_api_to_normalized,
        )

        # Simulate Events API raw event
        raw_api_event = {
            "id": "99999",
            "type": "PushEvent",
            "repo": {"name": "owner/repo"},
            "payload": {"after": "deadbeef"},
            "created_at": "2026-01-15T10:00:00Z",
        }
        api_normalized = map_events_api_to_normalized(raw_api_event, "inst-1")
        assert api_normalized is not None

        # Simulate webhook payload (same push, same after SHA)
        webhook_payload = {
            "after": "deadbeef",
            "repository": {"full_name": "owner/repo"},
        }
        webhook_key = compute_dedup_key("push", "", webhook_payload)

        assert api_normalized.dedup_key == webhook_key
