"""Regression tests for bug #694 (CheckRunPoller cold-start flood).

Each test verifies one specific layer of the eight-layer defense in
depth (ADR-060 Section 9). For #694 to recur, ALL of these layers
would have to fail simultaneously.

Layer table:
    1. ETag (HTTP 304) -- adapter responsibility, covered separately
    2. HWM filter inside fetch() -- THIS FILE
    3. Cold-start _started_at timestamp fence -- THIS FILE (and ESP)
    4. is_replay flag from poll() to process() -- THIS FILE
    5. Pipeline source_primed check -- THIS FILE
    6. Content-based dedup -- existing pipeline test
    7. Trigger rate limit (Guard 7) -- existing aggregate guard test
    8. Per-PR concurrency (Guard 6) -- existing aggregate guard test
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from event_sourcing.core.historical_poller import CursorData, PollEvent

from syn_domain.contexts.github.services import (
    GitHubEventsCursor,
    GitHubRepoIngestionService,
)


# -- Test doubles ------------------------------------------------------------


class MemoryCursorStore:
    """In-memory CursorStore for testing."""

    def __init__(self, initial: dict[str, CursorData] | None = None) -> None:
        self._cursors: dict[str, CursorData] = dict(initial or {})

    async def save(self, source_key: str, cursor: CursorData) -> None:
        self._cursors[source_key] = cursor

    async def load(self, source_key: str) -> CursorData | None:
        return self._cursors.get(source_key)

    async def load_all(self) -> dict[str, CursorData]:
        return dict(self._cursors)


class MockEventsAPI:
    """In-memory ``GitHubEventsAPIPort`` returning a fixed set of events."""

    def __init__(self, events: list[dict[str, Any]] | None = None) -> None:
        from syn_domain.contexts.github.slices.event_pipeline.ports import (
            EventsAPIResult,
        )

        self._events = list(events or [])
        self._etag = "etag-1"
        self._result_cls = EventsAPIResult
        self.fetch_count = 0

    def set_events(self, events: list[dict[str, Any]], etag: str = "etag-2") -> None:
        self._events = list(events)
        self._etag = etag

    async def fetch_repo_events(
        self,
        owner: str,  # noqa: ARG002
        repo: str,  # noqa: ARG002
        installation_id: str,  # noqa: ARG002
        etag: str | None = None,  # noqa: ARG002
    ) -> Any:  # noqa: ANN401
        self.fetch_count += 1
        return self._result_cls(
            events=list(self._events),
            has_new=bool(self._events),
            etag=self._etag,
            poll_interval_hint=60,
        )


class CapturingPipeline:
    """Captures every event passed to ``ingest()`` and the is_replay marker."""

    def __init__(self) -> None:
        self.ingested: list[Any] = []

    async def ingest(self, event: Any) -> Any:  # noqa: ANN401
        self.ingested.append(event)

        @dataclasses.dataclass
        class _Result:
            status: str = "processed"
            triggers_fired: tuple[str, ...] = ()

        return _Result()


def _raw_event(event_id: str, *, minutes_ago: int, event_type: str = "PushEvent") -> dict[str, Any]:
    ts = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    return {
        "id": event_id,
        "type": event_type,
        "repo": {"name": "owner/repo"},
        "payload": {"ref": "refs/heads/main", "after": f"sha-{event_id}"},
        "created_at": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _future_raw_event(event_id: str) -> dict[str, Any]:
    ts = datetime.now(UTC) + timedelta(seconds=2)
    return {
        "id": event_id,
        "type": "PushEvent",
        "repo": {"name": "owner/repo"},
        "payload": {"ref": "refs/heads/main", "after": f"sha-{event_id}"},
        "created_at": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _make_service(
    events_api: MockEventsAPI,
    pipeline: CapturingPipeline,
    cursor_store: MemoryCursorStore | None = None,
) -> GitHubRepoIngestionService:
    service = GitHubRepoIngestionService(
        events_api=events_api,  # type: ignore[arg-type]
        pipeline=pipeline,  # type: ignore[arg-type]
        cursor_store=cursor_store or MemoryCursorStore(),
    )
    service.set_installation_ids({"owner/repo": "inst-1"})
    return service


# -- Layer 2: HWM filter inside fetch() --------------------------------------


@pytest.mark.asyncio
class TestLayer2HWMFilter:
    """Layer 2 (THE PRINCIPAL #694 FIX): HWM filter rejects re-delivered events."""

    async def test_hwm_filter_drops_re_delivered_events(self) -> None:
        """After cursor saved with last_event_id=N, future fetch() drops id<=N."""
        # Pre-seed cursor with HWM at "100"
        store = MemoryCursorStore(
            initial={
                "owner/repo": GitHubEventsCursor(
                    etag="prev-etag", last_event_id="100",
                ).to_cursor_data(),
            }
        )
        # GitHub re-delivers historical events with ids 50, 75, 100 -- all <= HWM
        api = MockEventsAPI(events=[
            _future_raw_event("100"),
            _future_raw_event("75"),
            _future_raw_event("50"),
        ])
        pipeline = CapturingPipeline()
        service = _make_service(api, pipeline, store)
        await service.initialize()

        await service.poll("owner/repo")

        assert pipeline.ingested == [], (
            "HWM filter must drop all events with id <= cursor.last_event_id "
            "(principal #694 fix)"
        )

    async def test_hwm_filter_keeps_events_with_id_greater_than_hwm(self) -> None:
        """Events with id > HWM pass through and update the cursor."""
        store = MemoryCursorStore(
            initial={
                "owner/repo": GitHubEventsCursor(
                    etag="prev-etag", last_event_id="100",
                ).to_cursor_data(),
            }
        )
        # Mix: 50/100 should drop, 150/200 should pass
        api = MockEventsAPI(events=[
            _future_raw_event("200"),
            _future_raw_event("150"),
            _future_raw_event("100"),
            _future_raw_event("50"),
        ])
        pipeline = CapturingPipeline()
        service = _make_service(api, pipeline, store)
        await service.initialize()

        await service.poll("owner/repo")

        ingested_shas = {e.payload.get("after") for e in pipeline.ingested}
        assert ingested_shas == {"sha-150", "sha-200"}, (
            "Only events with id > HWM should pass through"
        )

    async def test_hwm_seeded_from_persisted_cursor_on_initialize(self) -> None:
        """initialize() must populate _high_water_marks from cursor_store.

        Critical for cold->crash->warm scenario: the cold-start poll
        primed the persisted cursor but then crashed before in-memory
        state was used. Without HWM seeding on restart, the warm poll
        would have an empty HWM and re-deliver everything.
        """
        store = MemoryCursorStore(
            initial={
                "owner/repo": GitHubEventsCursor(
                    etag="persisted", last_event_id="42",
                ).to_cursor_data(),
            }
        )
        api = MockEventsAPI(events=[])
        pipeline = CapturingPipeline()
        service = _make_service(api, pipeline, store)

        await service.initialize()

        seeded = service._high_water_marks.get("owner/repo")  # noqa: SLF001
        assert seeded is not None
        assert seeded.last_event_id == "42"
        assert seeded.etag == "persisted"

    async def test_multiple_repos_have_independent_hwm(self) -> None:
        """HWM is per-source_key, not global."""
        store = MemoryCursorStore(
            initial={
                "owner/repo-a": GitHubEventsCursor(
                    etag="a", last_event_id="100",
                ).to_cursor_data(),
                "owner/repo-b": GitHubEventsCursor(
                    etag="b", last_event_id="200",
                ).to_cursor_data(),
            }
        )
        api = MockEventsAPI()
        pipeline = CapturingPipeline()
        service = _make_service(api, pipeline, store)
        service.set_installation_ids({
            "owner/repo-a": "inst-1",
            "owner/repo-b": "inst-1",
        })
        await service.initialize()

        assert service._high_water_marks["owner/repo-a"].last_event_id == "100"  # noqa: SLF001
        assert service._high_water_marks["owner/repo-b"].last_event_id == "200"  # noqa: SLF001

    async def test_malformed_event_id_does_not_get_through_hwm(self) -> None:
        """Malformed event IDs are rejected (safer than re-process)."""
        store = MemoryCursorStore(
            initial={
                "owner/repo": GitHubEventsCursor(
                    etag="prev", last_event_id="42",
                ).to_cursor_data(),
            }
        )
        api = MockEventsAPI(events=[
            _future_raw_event("not-a-number"),
        ])
        pipeline = CapturingPipeline()
        service = _make_service(api, pipeline, store)
        await service.initialize()

        await service.poll("owner/repo")

        assert pipeline.ingested == [], (
            "Malformed event ID must not bypass the HWM filter"
        )


# -- Layer 3: Cold-start timestamp fence -------------------------------------


@pytest.mark.asyncio
class TestLayer3ColdStartFence:
    """Layer 3: ESP HistoricalPoller's _started_at timestamp fence."""

    async def test_cold_start_skips_historical_events(self) -> None:
        """First-ever poll filters events created before _started_at."""
        api = MockEventsAPI(events=[
            _raw_event("evt-old", minutes_ago=30),
        ])
        pipeline = CapturingPipeline()
        service = _make_service(api, pipeline)
        await service.initialize()

        await service.poll("owner/repo")

        assert pipeline.ingested == [], (
            "Cold-start fence must filter events older than _started_at"
        )


# -- Layers 4 + 5: is_replay -> source_primed=False --------------------------


@pytest.mark.asyncio
class TestLayer4IsReplay:
    """Layers 4 + 5: ESP signals is_replay=True; service marks events unprimed."""

    async def test_replay_events_carry_source_primed_false(self) -> None:
        """A post-startup event on cold-start path must be marked unprimed."""
        api = MockEventsAPI(events=[
            _future_raw_event("evt-now"),
        ])
        pipeline = CapturingPipeline()
        service = _make_service(api, pipeline)
        await service.initialize()

        await service.poll("owner/repo")

        assert len(pipeline.ingested) == 1, "Future event must pass cold-start fence"
        assert pipeline.ingested[0].source_primed is False, (
            "Cold-start replay events must carry source_primed=False so the "
            "pipeline (Layer 5) skips trigger evaluation"
        )

    async def test_warm_start_does_not_mark_events_unprimed(self) -> None:
        """Warm-start events have source_primed=True (default)."""
        store = MemoryCursorStore(
            initial={
                "owner/repo": GitHubEventsCursor(
                    etag="prev", last_event_id="0",
                ).to_cursor_data(),
            }
        )
        api = MockEventsAPI(events=[
            _raw_event("100", minutes_ago=30),
        ])
        pipeline = CapturingPipeline()
        service = _make_service(api, pipeline, store)
        await service.initialize()

        await service.poll("owner/repo")

        assert len(pipeline.ingested) == 1
        assert pipeline.ingested[0].source_primed is True, (
            "Warm-start events must NOT be marked unprimed"
        )

    async def test_process_passes_is_replay_true_through_to_pipeline_marker(
        self,
    ) -> None:
        """Direct unit test: process(is_replay=True) marks events source_primed=False."""
        from syn_domain.contexts.github.slices.event_pipeline.normalized_event import (
            EventSource,
            NormalizedEvent,
        )

        api = MockEventsAPI()
        pipeline = CapturingPipeline()
        service = _make_service(api, pipeline)

        event = NormalizedEvent(
            event_type="push",
            action="",
            repository="owner/repo",
            installation_id="inst-1",
            payload={"after": "sha-x"},
            dedup_key="dk-1",
            source=EventSource.EVENTS_API,
            received_at=datetime.now(UTC),
            source_primed=True,
        )

        # Bypass mapper by stubbing it to return our event directly
        import syn_domain.contexts.github.services.event_ingestion as ei

        original_mapper = ei.map_events_api_to_normalized
        ei.map_events_api_to_normalized = lambda raw, inst: event  # type: ignore[assignment]
        try:
            await service.process(
                "owner/repo",
                [PollEvent(created_at=datetime.now(UTC), data={"id": "1"})],
                is_replay=True,
            )
        finally:
            ei.map_events_api_to_normalized = original_mapper  # type: ignore[assignment]

        assert len(pipeline.ingested) == 1
        assert pipeline.ingested[0].source_primed is False


# -- End-to-end #694 scenario ------------------------------------------------


@pytest.mark.asyncio
class TestFull694Scenario:
    """End-to-end: a fresh stack must not re-process historical events."""

    async def test_fresh_stack_cold_then_warm_zero_redelivery(self) -> None:
        """Simulate the exact #694 scenario.

        - Fresh install (no cursor, no HWM).
        - First poll: GitHub returns 5 historical PR events from days ago.
        - Cold-start fence drops all 5. HWM is now seeded with max id seen.
        - Second poll: GitHub returns the SAME 5 events again (ETag changed).
        - HWM filter must reject all 5 -- pipeline.ingested stays empty.

        Without the #694 fix this second poll would flood the pipeline.
        """
        historical = [
            _raw_event(str(100 + i), minutes_ago=60 * (24 + i))
            for i in range(5)
        ]
        api = MockEventsAPI(events=historical)
        pipeline = CapturingPipeline()
        service = _make_service(api, pipeline)
        await service.initialize()

        # Cold start: timestamp fence drops all historical events
        await service.poll("owner/repo")
        assert pipeline.ingested == [], "Cold start must drop historical events"

        # Same events come back on warm-start re-delivery
        api.set_events(historical, etag="etag-after-change")
        await service.poll("owner/repo")

        assert pipeline.ingested == [], (
            "FAIL #694 REGRESSION: warm-start re-delivery flooded the pipeline. "
            "HWM filter (Layer 2) must reject events with id <= last_event_id."
        )
