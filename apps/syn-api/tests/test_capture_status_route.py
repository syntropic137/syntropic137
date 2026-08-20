"""The capture indicator has to be answerable, and it has to be right.

Rows here are built to match `query_recent_by_types`' actual contract - an
ENVELOPE with identity and time at the top level and the capture payload nested
under `data`. The first version of this file invented a flattened shape taken
from the WRITE path, and so certified a projection that read every payload
field from the wrong place: every healthy row came back UNKNOWN needing
backfill, and these tests passed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from syn_adapters.workspace_backends.agentic.capture_observation import (
    SESSION_CAPTURE_OBSERVATION,
    CaptureObservationData,
)
from syn_api.routes.capture import _to_entry, get_capture_status

if TYPE_CHECKING:
    from collections.abc import Mapping, MutableMapping, Sequence

RECORDED = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


def _payload(**overrides: object) -> Mapping[str, object]:
    """Built through the real observation model, so a renamed field fails here.

    Serialised via JSON like the storage path does, rather than handed over as
    live Python objects, so the test sees what a reader actually gets back.
    """
    data = CaptureObservationData(
        state="captured",
        needs_backfill=False,
        reason=None,
        store_url="https://sessions.example.com",
        origin_environment="container",
        origin_deployment="syntropic137__development",
        expected_store_url="https://sessions.example.com",
        expected_deployment="syntropic137__development",
        expected_sessions=True,
        partition="e-1/w-1",
    )
    serialised: MutableMapping[str, object] = json.loads(data.model_dump_json())
    serialised["workspace_id"] = "w-1"
    serialised.update(overrides)
    return serialised


def _row(session_id: str | None = "s-1", **payload_overrides: object) -> Mapping[str, object]:
    """One row exactly as the query adapter returns it."""
    return {
        "time": RECORDED.isoformat(),
        "event_type": SESSION_CAPTURE_OBSERVATION,
        "session_id": session_id,
        "execution_id": "e-1",
        "phase_id": "p-1",
        "data": _payload(**payload_overrides),
    }


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


class TestTheRealRowShape:
    """These are the assertions the invented shape could not make."""

    @pytest.mark.unit
    def test_a_healthy_row_is_not_reported_as_needing_backfill(self) -> None:
        entry = _to_entry(_row())

        assert entry is not None
        assert entry.state == "captured"
        assert entry.needs_backfill is False

    @pytest.mark.unit
    def test_payload_fields_are_read_from_the_nested_envelope(self) -> None:
        entry = _to_entry(_row())

        assert entry is not None
        # Each of these was None under the flattened misreading.
        assert entry.partition == "e-1/w-1"
        assert entry.workspace_id == "w-1"
        assert entry.origin_deployment == "syntropic137__development"
        assert entry.expected_deployment == "syntropic137__development"

    @pytest.mark.unit
    def test_the_timestamp_is_parsed_from_an_iso_string(self) -> None:
        """The adapter hands back a string, not a datetime."""
        entry = _to_entry(_row())

        assert entry is not None
        assert entry.recorded_at == RECORDED


class TestTheBiasIsTowardsReportingWork:
    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("state", "expected"),
        [
            ("captured", False),
            ("disabled", False),
            ("failed", True),
            ("incomplete", True),
            ("unknown", True),
        ],
    )
    def test_only_a_settled_verdict_closes_the_case(self, state: str, expected: bool) -> None:
        entry = _to_entry(_row(state=state))

        assert entry is not None
        assert entry.needs_backfill is expected

    @pytest.mark.unit
    def test_a_lying_flag_cannot_close_a_failed_case(self) -> None:
        """needs_backfill is derived, never trusted from the payload.

        A stored flag disagreeing with its own state - version skew, a partial
        write - would otherwise silently close a case it cannot close.
        """
        entry = _to_entry(_row(state="failed", needs_backfill=False))

        assert entry is not None
        assert entry.needs_backfill is True

    @pytest.mark.unit
    def test_an_unreadable_schema_version_is_unknown(self) -> None:
        """Fields may not mean what they are named across a version bump."""
        entry = _to_entry(_row(schema_version=999))

        assert entry is not None
        assert entry.state == "unknown"
        assert entry.needs_backfill is True

    @pytest.mark.unit
    @pytest.mark.parametrize("state", ["", "CAPTURED", "definitely-fine", None])
    def test_an_unrecognised_state_is_never_echoed_back(self, state: object) -> None:
        """Including the uppercase spelling, which is not what is recorded."""
        entry = _to_entry(_row(state=state))

        assert entry is not None
        assert entry.state == "unknown"
        assert entry.needs_backfill is True


class TestCaptureStatusEndpoint:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_it_queries_only_capture_observations(self, _patch_store) -> None:
        store = _patch_store([_row()])

        await get_capture_status(limit=25, needs_backfill=False)

        assert store.seen == {
            "event_types": [SESSION_CAPTURE_OBSERVATION],
            "limit": 25,
        }

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_the_backlog_count_survives_filtering(self, _patch_store) -> None:
        """Filtering to the backlog must not hide how big the backlog is."""
        _patch_store(
            [
                _row(session_id="s-1"),
                _row(session_id="s-2", state="unknown"),
                _row(session_id="s-3", state="failed"),
            ]
        )

        unfiltered = await get_capture_status(limit=50, needs_backfill=False)
        filtered = await get_capture_status(limit=50, needs_backfill=True)

        assert unfiltered.total == 3
        assert unfiltered.needs_backfill_count == 2
        assert filtered.total == 2
        assert filtered.needs_backfill_count == 2
        assert {e.session_id for e in filtered.entries} == {"s-2", "s-3"}

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_a_full_window_is_reported_as_truncated(self, _patch_store) -> None:
        """The limit is applied BEFORE the filter, in the database.

        Without this flag a caller could read an empty backlog off a page that
        never reached the failures - a wrong answer, not a missing feature.
        """
        _patch_store([_row(session_id=f"s-{i}") for i in range(3)])

        result = await get_capture_status(limit=3, needs_backfill=True)

        assert result.truncated is True
        assert result.scanned == 3
        assert result.entries == []
        # An empty backlog on a truncated scan proves nothing, and the flag is
        # what tells the caller so.
        assert result.needs_backfill_count == 0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_a_sessionless_verdict_is_counted_not_swallowed(self, _patch_store) -> None:
        """A response that omitted it could read as all-clear."""
        _patch_store([_row(session_id=None, state="failed")])

        result = await get_capture_status(limit=50, needs_backfill=False)

        assert result.entries == []
        assert result.unattributable_count == 1

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_a_disabled_capture_is_not_a_backfill_candidate(self, _patch_store) -> None:
        """Capture being off is not a transcript that went missing."""
        _patch_store([_row(state="disabled")])

        result = await get_capture_status(limit=50, needs_backfill=True)

        assert result.needs_backfill_count == 0
        assert result.entries == []


class TestReasonCannotCarryAStoreUrl:
    """The exporter interpolates the store URL into its mismatch verdict.

    capture_result quotes both the reported and the configured store in one
    sentence. That URL is operator-supplied and can carry the write token in
    its userinfo, query, or host - the same reasoning that stopped the startup
    posture line logging any part of it.
    """

    TOKEN = "super-secret-write-token"

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "url",
        [
            "https://{token}@sessions.example.com",
            "https://sessions.example.com?write_token={token}",
            "https://{token}",
            "{token}://sessions.example.com",
        ],
    )
    def test_a_credential_bearing_url_never_reaches_the_response(self, url: str) -> None:
        reason = (
            f"exporter reported success against {url.format(token=self.TOKEN)!r}, "
            "not the configured store"
        )

        entry = _to_entry(_row(state="failed", reason=reason))

        assert entry is not None
        assert entry.reason is not None
        assert self.TOKEN not in entry.reason

    @pytest.mark.unit
    def test_the_diagnosis_survives_the_scrub(self) -> None:
        """Redaction must not reduce the reason to noise."""
        entry = _to_entry(
            _row(
                state="failed",
                reason="exporter reported success against 'https://other.example', "
                "not the configured 'https://sessions.example.com'",
            )
        )

        assert entry is not None
        assert entry.reason is not None
        assert "reported success against" in entry.reason
        assert "not the configured" in entry.reason

    @pytest.mark.unit
    def test_a_reason_without_a_url_is_untouched(self) -> None:
        entry = _to_entry(_row(state="failed", reason="missing required env var SESSION_STORE_URL"))

        assert entry is not None
        assert entry.reason == "missing required env var SESSION_STORE_URL"
