"""Tests for EventPipeline — routing, dedup, and fail-open behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from syn_domain.contexts.github._shared.trigger_query_store import InMemoryTriggerQueryStore
from syn_domain.contexts.github.slices.evaluate_webhook.EvaluateWebhookHandler import (
    EvaluateWebhookHandler,
)
from syn_domain.contexts.github.slices.event_pipeline.normalized_event import (
    EventSource,
    NormalizedEvent,
)
from syn_domain.contexts.github.slices.event_pipeline.pipeline import EventPipeline

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class NullRepository:
    """No-op repository for tests that don't need persistence."""

    async def get_by_id(self, aggregate_id: str) -> None:
        return None

    async def save(self, aggregate: object) -> None:
        pass


class InMemoryDedup:
    """Simple in-memory dedup for tests."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    async def is_duplicate(self, dedup_key: str) -> bool:
        if dedup_key in self._seen:
            return True
        self._seen.add(dedup_key)
        return False

    async def mark_seen(self, dedup_key: str) -> None:
        self._seen.add(dedup_key)


class FailingDedup:
    """Dedup adapter that always raises (for fail-open testing)."""

    async def is_duplicate(self, dedup_key: str) -> bool:
        msg = "Redis connection refused"
        raise ConnectionError(msg)

    async def mark_seen(self, dedup_key: str) -> None:
        msg = "Redis connection refused"
        raise ConnectionError(msg)


def _make_event(
    event_type: str = "push",
    action: str = "",
    dedup_key: str = "test-key-1",
    repository: str = "owner/repo",
    installation_id: str = "12345",
    delivery_id: str = "delivery-abc",
    source_primed: bool = True,
) -> NormalizedEvent:
    return NormalizedEvent(
        event_type=event_type,
        action=action,
        repository=repository,
        installation_id=installation_id,
        dedup_key=dedup_key,
        source=EventSource.WEBHOOK,
        payload={"repository": {"full_name": repository}},
        received_at=datetime.now(UTC),
        delivery_id=delivery_id,
        source_primed=source_primed,
    )


def _make_pipeline(
    dedup: object | None = None, store: InMemoryTriggerQueryStore | None = None
) -> EventPipeline:
    trigger_store = store or InMemoryTriggerQueryStore()
    evaluator = EvaluateWebhookHandler(
        store=trigger_store,
        repository=NullRepository(),
    )
    return EventPipeline(
        dedup=dedup or InMemoryDedup(),
        evaluator=evaluator,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPipelineDedup:
    @pytest.mark.asyncio
    async def test_new_event_is_processed(self) -> None:
        pipeline = _make_pipeline()
        result = await pipeline.ingest(_make_event())
        assert result.status == "processed"

    @pytest.mark.asyncio
    async def test_duplicate_event_is_skipped(self) -> None:
        pipeline = _make_pipeline()
        event = _make_event(dedup_key="same-key")

        first = await pipeline.ingest(event)
        second = await pipeline.ingest(event)

        assert first.status == "processed"
        assert second.status == "deduplicated"

    @pytest.mark.asyncio
    async def test_different_keys_both_process(self) -> None:
        pipeline = _make_pipeline()

        r1 = await pipeline.ingest(_make_event(dedup_key="key-1"))
        r2 = await pipeline.ingest(_make_event(dedup_key="key-2"))

        assert r1.status == "processed"
        assert r2.status == "processed"


class TestPipelineFailOpen:
    @pytest.mark.asyncio
    async def test_dedup_failure_still_processes(self) -> None:
        """When dedup backend is down, events should still be processed."""
        pipeline = _make_pipeline(dedup=FailingDedup())
        result = await pipeline.ingest(_make_event())
        assert result.status == "processed"


class TestPipelineResult:
    @pytest.mark.asyncio
    async def test_result_contains_event_type(self) -> None:
        pipeline = _make_pipeline()
        result = await pipeline.ingest(_make_event(event_type="pull_request", action="opened"))
        assert result.event_type == "pull_request"

    @pytest.mark.asyncio
    async def test_no_triggers_returns_empty_lists(self) -> None:
        """When no triggers match, fired and deferred should be empty."""
        pipeline = _make_pipeline()
        result = await pipeline.ingest(_make_event())
        assert result.triggers_fired == []
        assert result.deferred == []


class TestPipelineWithTriggers:
    @pytest.mark.asyncio
    async def test_matching_trigger_fires(self) -> None:
        """When a trigger matches, its ID appears in triggers_fired."""
        store = InMemoryTriggerQueryStore()
        await store.index_trigger(
            trigger_id="tr-001",
            name="test-trigger",
            event="push",
            repository="owner/repo",
            workflow_id="wf-001",
            conditions=[],
            input_mapping={},
            config=_make_config(),
            installation_id="12345",
            created_by="test",
            status="active",
        )

        pipeline = _make_pipeline(store=store)

        result = await pipeline.ingest(_make_event(event_type="push"))
        assert "tr-001" in result.triggers_fired


class TestPipelineColdStartFence:
    """ADR-060 Layer 5: source_primed=False skips trigger evaluation."""

    @pytest.mark.asyncio
    async def test_unprimed_event_skips_trigger_evaluation(self) -> None:
        """An unprimed event must not fire any matching trigger."""
        store = InMemoryTriggerQueryStore()
        await store.index_trigger(
            trigger_id="tr-cold",
            name="cold-start-trigger",
            event="push",
            repository="owner/repo",
            workflow_id="wf-001",
            conditions=[],
            input_mapping={},
            config=_make_config(),
            installation_id="12345",
            created_by="test",
            status="active",
        )
        pipeline = _make_pipeline(store=store)

        result = await pipeline.ingest(
            _make_event(event_type="push", source_primed=False),
        )

        assert result.status == "processed"
        assert result.triggers_fired == []
        assert result.deferred == []
        assert result.blocked == []

    @pytest.mark.asyncio
    async def test_unprimed_event_does_not_notify_observers(self) -> None:
        """Cold-start replays must not register SHAs via observer callbacks."""
        observed: list[NormalizedEvent] = []

        async def observer(event: NormalizedEvent) -> None:
            observed.append(event)

        pipeline = _make_pipeline()
        pipeline.add_observer(observer)

        await pipeline.ingest(_make_event(source_primed=False))

        assert observed == []

    @pytest.mark.asyncio
    async def test_primed_event_still_fires_after_unprimed(self) -> None:
        """The fence is per-event; a later primed event must still fire."""
        store = InMemoryTriggerQueryStore()
        await store.index_trigger(
            trigger_id="tr-primed",
            name="primed-trigger",
            event="push",
            repository="owner/repo",
            workflow_id="wf-001",
            conditions=[],
            input_mapping={},
            config=_make_config(),
            installation_id="12345",
            created_by="test",
            status="active",
        )
        pipeline = _make_pipeline(store=store)

        cold = await pipeline.ingest(
            _make_event(dedup_key="cold-1", source_primed=False),
        )
        warm = await pipeline.ingest(
            _make_event(dedup_key="warm-1", source_primed=True),
        )

        assert cold.triggers_fired == []
        assert "tr-primed" in warm.triggers_fired


def _make_config() -> Any:  # noqa: ANN401
    from syn_domain.contexts.github.domain.aggregate_trigger.TriggerConfig import TriggerConfig

    return TriggerConfig()
