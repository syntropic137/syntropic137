"""Regression tests for cold-start event flood (ADR-060 section 7).

On fresh install (empty Postgres), the Events API poller fetches ALL
historical events and processes them as "new." Before the fix, this
causes every trigger to fire for every historical event, creating
a flood of workflow executions and OOM-killing the Docker host.

These tests validate the HistoricalPoller cold-start fence:
- Historical events (created before poller startup) are skipped
- Post-startup events are processed
- Cold-start events carry source_primed=False (belt-and-suspenders)
- Warm restart processes all events normally
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from syn_domain.contexts.github.slices.event_pipeline.normalized_event import (
    EventSource,
    NormalizedEvent,
)
from syn_domain.contexts.github.slices.event_pipeline.pipeline import EventPipeline, PipelineResult

if TYPE_CHECKING:
    from event_sourcing.core.historical_poller import CursorData

# ============================================================================
# Test infrastructure
# ============================================================================


class MemoryCursorStore:
    """In-memory cursor store for testing."""

    def __init__(self, initial: dict[str, CursorData] | None = None) -> None:
        self._cursors: dict[str, CursorData] = dict(initial) if initial else {}

    async def save(self, source_key: str, cursor: CursorData) -> None:
        self._cursors[source_key] = cursor

    async def load(self, source_key: str) -> CursorData | None:
        return self._cursors.get(source_key)

    async def load_all(self) -> dict[str, CursorData]:
        return dict(self._cursors)


class TrackingPipeline:
    """Pipeline wrapper that tracks what gets ingested and with what source_primed value."""

    def __init__(self, real_pipeline: EventPipeline) -> None:
        self._real = real_pipeline
        self.ingested: list[NormalizedEvent] = []

    async def ingest(self, event: NormalizedEvent) -> PipelineResult:
        self.ingested.append(event)
        return await self._real.ingest(event)

    @property
    def primed_events(self) -> list[NormalizedEvent]:
        return [e for e in self.ingested if e.source_primed]

    @property
    def unprimed_events(self) -> list[NormalizedEvent]:
        return [e for e in self.ingested if not e.source_primed]

    def add_observer(self, callback: object) -> None:
        """Proxy for pipeline observer registration."""
        self._real.add_observer(callback)  # type: ignore[arg-type]


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


class TrackingEvaluator:
    """Evaluator that tracks trigger fires instead of doing real work."""

    def __init__(self) -> None:
        self.evaluations: list[dict[str, object]] = []

    async def evaluate(
        self,
        event: str,
        repository: str,
        installation_id: str,
        payload: dict[str, Any],
    ) -> list[object]:
        self.evaluations.append(
            {
                "event": event,
                "repository": repository,
                "installation_id": installation_id,
            }
        )
        return []


def _make_raw_event(
    event_id: str,
    event_type: str,
    repo: str,
    minutes_ago: float,
) -> dict[str, Any]:
    """Create a raw Events API payload with a specific created_at time."""
    created = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    created_str = created.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "id": event_id,
        "type": event_type,
        "repo": {"name": repo},
        "payload": {"ref": "refs/heads/main", "after": f"sha-{event_id}"},
        "created_at": created_str,
    }


# ============================================================================
# Cold-start regression tests
# ============================================================================


@pytest.mark.asyncio
class TestColdStartFence:
    """Regression tests for cold-start event flood (ADR-060 section 7).

    These tests exercise the full path: GitHubEventPoller -> pipeline.ingest()
    and verify that historical events from the Events API do NOT fire triggers
    on fresh install.
    """

    async def test_fresh_install_historical_events_do_not_fire_triggers(self) -> None:
        """REGRESSION: fresh install with historical events must fire zero triggers.

        Before fix: all events pass dedup (empty), pass guards (no history),
        and fire triggers -- causing OOM from concurrent container launches.
        After fix: HistoricalPoller filters events with created_at < started_at.
        """
        evaluator = TrackingEvaluator()
        pipeline = EventPipeline(dedup=InMemoryDedup(), evaluator=evaluator)  # type: ignore[arg-type]
        tracking = TrackingPipeline(pipeline)

        # 10 events, all from 10-60 minutes ago (historical)
        historical_events = [
            _make_raw_event(
                event_id=str(i),
                event_type="PushEvent",
                repo="owner/repo",
                minutes_ago=10 + i * 5,
            )
            for i in range(10)
        ]

        from syn_domain.contexts.github._shared.trigger_query_store import (
            InMemoryTriggerQueryStore,
        )
        from syn_domain.contexts.github.domain.aggregate_trigger.TriggerConfig import TriggerConfig

        trigger_store = InMemoryTriggerQueryStore()
        await trigger_store.index_trigger(
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

        # This is the key assertion: after the fix, GitHubEventPoller
        # uses GitHubRepoPoller(HistoricalPoller) which filters historical
        # events on cold start. The evaluator should receive zero calls.
        #
        # Before the fix, this uses the old GitHubEventPoller which has
        # no cold-start awareness, so all 10 events would be evaluated.

        # For now, test at the pipeline level directly -- the poller
        # conversion will make this test pass end-to-end
        for raw in historical_events:
            from syn_domain.contexts.github import map_events_api_to_normalized

            normalized = map_events_api_to_normalized(raw, "inst-1")
            if normalized:
                # Cold-start events should have source_primed=False
                cold_event = dataclasses.replace(normalized, source_primed=False)
                await tracking.ingest(cold_event)

        # Pipeline should skip trigger evaluation for unprimed events
        assert evaluator.evaluations == [], (
            f"Expected zero trigger evaluations for cold-start events, "
            f"got {len(evaluator.evaluations)}. Historical events must not fire triggers."
        )

    async def test_post_startup_events_are_processed(self) -> None:
        """Events created AFTER poller startup must be processed and evaluated."""
        evaluator = TrackingEvaluator()
        pipeline = EventPipeline(dedup=InMemoryDedup(), evaluator=evaluator)  # type: ignore[arg-type]
        tracking = TrackingPipeline(pipeline)

        # Event created 0 minutes ago (after startup)
        new_event = _make_raw_event("new-1", "PushEvent", "owner/repo", minutes_ago=0)

        from syn_domain.contexts.github import map_events_api_to_normalized

        normalized = map_events_api_to_normalized(new_event, "inst-1")
        assert normalized is not None

        # Post-startup events should have source_primed=True (default)
        await tracking.ingest(normalized)

        assert len(evaluator.evaluations) == 1, (
            "Post-startup events must be evaluated for trigger matches"
        )

    async def test_source_primed_false_skips_trigger_evaluation(self) -> None:
        """Pipeline skips trigger evaluation when source_primed=False."""
        evaluator = TrackingEvaluator()
        pipeline = EventPipeline(dedup=InMemoryDedup(), evaluator=evaluator)  # type: ignore[arg-type]

        event = NormalizedEvent(
            event_type="push",
            action="",
            repository="owner/repo",
            installation_id="inst-1",
            dedup_key="test-dedup-key",
            source=EventSource.EVENTS_API,
            payload={"ref": "refs/heads/main"},
            received_at=datetime.now(UTC),
            source_primed=False,
        )

        result = await pipeline.ingest(event)

        assert result.status == "processed"
        assert evaluator.evaluations == [], (
            "Pipeline must skip trigger evaluation when source_primed=False"
        )

    async def test_source_primed_true_evaluates_triggers(self) -> None:
        """Pipeline evaluates triggers when source_primed=True (default)."""
        evaluator = TrackingEvaluator()
        pipeline = EventPipeline(dedup=InMemoryDedup(), evaluator=evaluator)  # type: ignore[arg-type]

        event = NormalizedEvent(
            event_type="push",
            action="",
            repository="owner/repo",
            installation_id="inst-1",
            dedup_key="test-dedup-key-2",
            source=EventSource.EVENTS_API,
            payload={"ref": "refs/heads/main"},
            received_at=datetime.now(UTC),
            source_primed=True,
        )

        result = await pipeline.ingest(event)

        assert result.status == "processed"
        assert len(evaluator.evaluations) == 1, (
            "Pipeline must evaluate triggers when source_primed=True"
        )

    async def test_warm_restart_processes_all_events(self) -> None:
        """With existing cursor (warm start), events should have source_primed=True."""
        evaluator = TrackingEvaluator()
        pipeline = EventPipeline(dedup=InMemoryDedup(), evaluator=evaluator)  # type: ignore[arg-type]

        # Simulate warm-start event (source_primed=True is the default)
        event = NormalizedEvent(
            event_type="push",
            action="",
            repository="owner/repo",
            installation_id="inst-1",
            dedup_key="warm-restart-key",
            source=EventSource.EVENTS_API,
            payload={"ref": "refs/heads/main"},
            received_at=datetime.now(UTC),
            # source_primed defaults to True -- warm restart
        )

        await pipeline.ingest(event)

        assert len(evaluator.evaluations) == 1, "Warm restart events must be evaluated for triggers"


# ============================================================================
# End-to-end GitHubRepoPoller cold-start tests
# ============================================================================


def _make_mock_events_client(
    events: list[dict[str, Any]],
) -> object:
    """Create an in-memory ``GitHubEventsAPIPort`` implementation for tests."""
    from syn_domain.contexts.github.slices.event_pipeline.ports import EventsAPIResult

    class _MockClient:
        def __init__(self) -> None:
            self.call_count = 0
            self.last_etag: str | None = None

        async def fetch_repo_events(
            self,
            owner: str,
            repo: str,
            installation_id: str,
            etag: str | None = None,
        ) -> EventsAPIResult:
            self.call_count += 1
            self.last_etag = etag
            return EventsAPIResult(
                events=events,
                has_new=bool(events),
                etag="response-etag-1",
                poll_interval_hint=60,
            )

    return _MockClient()


@pytest.mark.asyncio
class TestRepoPollerColdStartFence:
    """End-to-end tests through GitHubRepoPoller.poll() -- the real code path.

    These tests wire up the actual GitHubRepoPoller(HistoricalPoller) and
    verify that the cold-start timestamp fence filters historical events.
    """

    async def test_cold_start_skips_historical_events(self) -> None:
        """CRITICAL: On cold start, historical events must NOT reach process().

        This is the core regression test. On fresh install (empty cursor store),
        GitHubRepoPoller.poll() calls HistoricalPoller.poll() which filters
        events with created_at < started_at.
        """

        from syn_api.services.github_event_poller import GitHubRepoPoller

        # 10 events, all from 10-60 minutes ago (historical)
        historical_events = [
            _make_raw_event(str(i), "PushEvent", "owner/repo", minutes_ago=10 + i * 5)
            for i in range(10)
        ]

        tracking = TrackingPipeline(
            EventPipeline(dedup=InMemoryDedup(), evaluator=TrackingEvaluator())  # type: ignore[arg-type]
        )
        mock_client = _make_mock_events_client(historical_events)

        repo_poller = GitHubRepoPoller(
            events_client=mock_client,  # type: ignore[arg-type]
            pipeline=tracking,  # type: ignore[arg-type]
            cursor_store=MemoryCursorStore(),
        )
        repo_poller.set_installation_ids({"owner/repo": "inst-1"})

        await repo_poller.initialize()
        await repo_poller.poll("owner/repo")

        # Cold-start fence should have filtered ALL events (all are historical)
        assert tracking.ingested == [], (
            f"Expected zero events ingested on cold start, got {len(tracking.ingested)}. "
            "HistoricalPoller must filter events with created_at < started_at."
        )

    async def test_warm_start_processes_old_events(self) -> None:
        """On warm start (existing cursor), even old events pass through.

        When the cursor store has an entry for the repo, HistoricalPoller
        treats it as warm start and processes all events regardless of
        their created_at timestamp.
        """
        from event_sourcing.core.historical_poller import CursorData

        from syn_api.services.github_event_poller import GitHubRepoPoller

        # Event from 30 minutes ago -- would be filtered on cold start
        old_events = [
            _make_raw_event("evt-1", "PushEvent", "owner/repo", minutes_ago=30),
        ]

        tracking = TrackingPipeline(
            EventPipeline(dedup=InMemoryDedup(), evaluator=TrackingEvaluator())  # type: ignore[arg-type]
        )
        mock_client = _make_mock_events_client(old_events)

        # Pre-populate cursor: this is a warm start
        cursor_store = MemoryCursorStore(initial={"owner/repo": CursorData(value="old-etag")})
        repo_poller = GitHubRepoPoller(
            events_client=mock_client,  # type: ignore[arg-type]
            pipeline=tracking,  # type: ignore[arg-type]
            cursor_store=cursor_store,
        )
        repo_poller.set_installation_ids({"owner/repo": "inst-1"})

        await repo_poller.initialize()
        await repo_poller.poll("owner/repo")

        # Warm start: all events pass through
        assert len(tracking.ingested) == 1, (
            f"Expected 1 event on warm start, got {len(tracking.ingested)}. "
            "Warm start must process all events regardless of timestamp."
        )
        # Warm start events should have source_primed=True
        assert tracking.ingested[0].source_primed is True

    async def test_second_poll_after_cold_start_is_warm(self) -> None:
        """After cold-start priming, the second poll processes all events.

        The state machine transition: cold start -> _prime() -> primed.
        Subsequent polls behave as warm start.
        """

        from syn_api.services.github_event_poller import GitHubRepoPoller

        historical_events = [
            _make_raw_event("evt-1", "PushEvent", "owner/repo", minutes_ago=30),
        ]

        tracking = TrackingPipeline(
            EventPipeline(dedup=InMemoryDedup(), evaluator=TrackingEvaluator())  # type: ignore[arg-type]
        )
        mock_client = _make_mock_events_client(historical_events)

        repo_poller = GitHubRepoPoller(
            events_client=mock_client,  # type: ignore[arg-type]
            pipeline=tracking,  # type: ignore[arg-type]
            cursor_store=MemoryCursorStore(),
        )
        repo_poller.set_installation_ids({"owner/repo": "inst-1"})

        await repo_poller.initialize()

        # First poll: cold start, historical events filtered
        await repo_poller.poll("owner/repo")
        assert tracking.ingested == [], "First poll (cold start) must skip historical events"

        # Source should now be primed
        assert "owner/repo" in repo_poller.primed_sources, (
            "After cold-start poll, source must be in primed_sources"
        )

        # Second poll: warm start, same historical events now pass through
        tracking.ingested.clear()
        await repo_poller.poll("owner/repo")
        assert len(tracking.ingested) == 1, (
            f"Second poll (warm) must process events, got {len(tracking.ingested)}"
        )

    async def test_cold_start_passes_post_startup_events(self) -> None:
        """Events created AFTER started_at pass the cold-start fence.

        On cold start, HistoricalPoller._prime() runs before process(),
        so the source is primed when process() runs. Events that pass
        the timestamp fence get source_primed=True (the source was
        primed by _prime()). The belt-and-suspenders source_primed=False
        only applies when pipeline.ingest() is called outside the
        HistoricalPoller path.
        """
        from syn_api.services.github_event_poller import GitHubRepoPoller

        tracking = TrackingPipeline(
            EventPipeline(dedup=InMemoryDedup(), evaluator=TrackingEvaluator())  # type: ignore[arg-type]
        )

        # Event created 2 seconds in the future -- guarantees it passes the
        # timestamp fence even with second-precision truncation
        future_ts = datetime.now(UTC) + timedelta(seconds=2)
        future_str = future_ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        recent_events = [
            {
                "id": "evt-now",
                "type": "PushEvent",
                "repo": {"name": "owner/repo"},
                "payload": {"ref": "refs/heads/main", "after": "sha-evt-now"},
                "created_at": future_str,
            },
        ]
        mock_client = _make_mock_events_client(recent_events)

        repo_poller = GitHubRepoPoller(
            events_client=mock_client,  # type: ignore[arg-type]
            pipeline=tracking,  # type: ignore[arg-type]
            cursor_store=MemoryCursorStore(),
        )
        repo_poller.set_installation_ids({"owner/repo": "inst-1"})

        await repo_poller.initialize()
        await repo_poller.poll("owner/repo")

        # Post-startup events pass the fence and get processed
        assert len(tracking.ingested) == 1, "Post-startup event should pass cold-start fence"
        # Source is primed by _prime() before process() runs on cold start
        assert tracking.ingested[0].source_primed is True

    async def test_etag_threaded_to_client(self) -> None:
        """Stored ETag from cursor is passed to the client on subsequent polls."""
        from event_sourcing.core.historical_poller import CursorData

        from syn_api.services.github_event_poller import GitHubRepoPoller

        mock_client = _make_mock_events_client([])

        cursor_store = MemoryCursorStore(
            initial={"owner/repo": CursorData(value="stored-etag-abc")}
        )
        repo_poller = GitHubRepoPoller(
            events_client=mock_client,  # type: ignore[arg-type]
            pipeline=EventPipeline(dedup=InMemoryDedup(), evaluator=TrackingEvaluator()),  # type: ignore[arg-type]
            cursor_store=cursor_store,
        )
        repo_poller.set_installation_ids({"owner/repo": "inst-1"})

        await repo_poller.initialize()
        await repo_poller.poll("owner/repo")

        # The stored ETag should have been passed to the client
        assert mock_client.last_etag == "stored-etag-abc", (  # type: ignore[union-attr]
            f"Expected stored ETag to be passed to client, got {mock_client.last_etag}"  # type: ignore[union-attr]
        )
