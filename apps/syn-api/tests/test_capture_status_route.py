"""The capture indicator has to be answerable, not just loggable.

Capture writes verdicts to the observability lane. Before this endpoint an
operator could see a startup warning and a log line per phase, but could not
ask the question that matters afterwards: WHICH sessions did not reach the
store. That is also precisely the work-list a backfill pass needs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from syn_api.routes.capture import _to_entry, get_capture_status

if TYPE_CHECKING:
    from collections.abc import Mapping, MutableMapping, Sequence

RECORDED = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


def _event(**overrides: object) -> Mapping[str, object]:
    event: MutableMapping[str, object] = {
        "event_type": "session_capture",
        "session_id": "s-1",
        "execution_id": "e-1",
        "phase_id": "p-1",
        "workspace_id": "w-1",
        "timestamp": RECORDED,
        "state": "CAPTURED",
        "needs_backfill": False,
        "reason": None,
        "partition": "e-1/w-1",
        "expected_deployment": "syntropic137__development",
        "origin_deployment": "syntropic137__development",
    }
    event.update(overrides)
    return event


class _Store:
    def __init__(self, events: Sequence[Mapping[str, object]]) -> None:
        self._events = events
        self.seen: Mapping[str, object] = {}

    async def query_recent_by_types(
        self, event_types: list[str], limit: int = 50
    ) -> Sequence[Mapping[str, object]]:
        self.seen = {"event_types": event_types, "limit": limit}
        return self._events


@pytest.fixture
def _patch_store(monkeypatch: pytest.MonkeyPatch):
    def _install(events: Sequence[Mapping[str, object]]) -> _Store:
        store = _Store(events)
        monkeypatch.setattr("syn_api.routes.capture.get_event_store", lambda: store)
        return store

    return _install


class TestEntryProjection:
    @pytest.mark.unit
    def test_a_healthy_capture_carries_its_partition(self) -> None:
        entry = _to_entry(_event())

        assert entry is not None
        # The partition is what a retry needs to FIND the transcripts again,
        # so it must survive into the work-list even on the success path.
        assert entry.partition == "e-1/w-1"
        assert entry.needs_backfill is False

    @pytest.mark.unit
    def test_an_event_without_a_session_id_is_dropped(self) -> None:
        """A row naming nothing to retry is worse than no row."""
        assert _to_entry(_event(session_id="")) is None
        assert _to_entry(_event(session_id=None)) is None

    @pytest.mark.unit
    def test_a_stateless_observation_is_unknown_and_needs_backfill(self) -> None:
        """ "We cannot tell" must never be recorded as "safely stored"."""
        event = dict(_event())
        del event["state"]
        del event["needs_backfill"]

        entry = _to_entry(event)

        assert entry is not None
        assert entry.state == "UNKNOWN"
        assert entry.needs_backfill is True


class TestCaptureStatusEndpoint:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_it_queries_only_capture_observations(self, _patch_store) -> None:
        store = _patch_store([_event()])

        await get_capture_status(limit=25, needs_backfill=False)

        assert store.seen == {"event_types": ["session_capture"], "limit": 25}

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_the_backlog_count_survives_filtering(self, _patch_store) -> None:
        """Filtering to the backlog must not hide how big the backlog is."""
        _patch_store(
            [
                _event(session_id="s-1"),
                _event(session_id="s-2", state="UNKNOWN", needs_backfill=True),
                _event(session_id="s-3", state="FAILED", needs_backfill=True),
            ]
        )

        unfiltered = await get_capture_status(limit=50, needs_backfill=False)
        filtered = await get_capture_status(limit=50, needs_backfill=True)

        assert unfiltered.total == 3
        assert unfiltered.needs_backfill_count == 2
        # total narrows to what was returned; the backlog count does not.
        assert filtered.total == 2
        assert filtered.needs_backfill_count == 2
        assert {e.session_id for e in filtered.entries} == {"s-2", "s-3"}

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_a_disabled_capture_is_not_a_backfill_candidate(self, _patch_store) -> None:
        """Capture being off is not a transcript that went missing."""
        _patch_store([_event(state="DISABLED", needs_backfill=False)])

        result = await get_capture_status(limit=50, needs_backfill=True)

        assert result.needs_backfill_count == 0
        assert result.entries == []
