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
    SUPPORTED_OBSERVATION_SCHEMA_VERSIONS,
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
    @pytest.mark.parametrize("lookalike", [True, 1.0, "1", None])
    def test_a_version_that_is_not_an_integer_is_unknown(self, lookalike: object) -> None:
        """True == 1 and 1.0 == 1, so membership alone would admit them.

        The stored payload is written by another process, so the reader cannot
        assume the writer's type discipline held.
        """
        entry = _to_entry(_row(schema_version=lookalike))

        assert entry is not None
        assert entry.state == "unknown"
        assert entry.needs_backfill is True

    @pytest.mark.unit
    def test_the_exporter_result_version_is_not_this_version(self) -> None:
        """These are two version namespaces, not one.

        This route validates the RECORDED OBSERVATION payload (state /
        needs_backfill / reason). The exporter's own result document
        (captured_everything / counters / origin) versions separately, and
        moved to 2 in agentic-session-exporter#20.

        The two were briefly coupled: this route imported the exporter's
        constant, which worked only while both happened to equal 1. Widening
        the exporter's set to {1, 2} silently widened this gate to accept a
        recorded shape nothing defines or writes. Reading either number as the
        other is exactly the misreading the field exists to prevent.

        Both sets now happen to be {1, 2} again - the observation payload gained
        `agent_session_ids` at version 2 - so this pins the observation set by
        VALUE rather than by comparison, and refuses a version outside it. If
        the exporter later moves to 3, this route must not follow.
        """
        assert frozenset({1, 2}) == SUPPORTED_OBSERVATION_SCHEMA_VERSIONS

        entry = _to_entry(_row(schema_version=3))

        assert entry is not None
        assert entry.state == "unknown"
        assert entry.needs_backfill is True

    @pytest.mark.unit
    def test_a_phase_reports_every_agent_session_it_produced(self) -> None:
        """The join from a host-owned phase to the agent-named transcripts.

        This is what makes a phase's sessions fetchable from the store, which
        keys on the agent-native id and knows nothing about syn137's uuid4.
        """
        entry = _to_entry(_row(agent_session_ids=["sess-codex", "sess-claude"]))

        assert entry is not None
        assert entry.agent_session_ids == ["sess-codex", "sess-claude"]

    @pytest.mark.unit
    @pytest.mark.parametrize("stored", [[], ["x"]], ids=["empty", "populated"])
    def test_a_schema_1_row_never_yields_agent_sessions(self, stored: object) -> None:
        """The field did not exist at schema 1.

        A schema 1 payload carrying the key did not get it from a writer of
        ours, so interpreting it under schema 2 semantics would mean trusting a
        shape nobody declared.
        """
        entry = _to_entry(_row(schema_version=1, agent_session_ids=stored))

        assert entry is not None
        assert entry.agent_session_ids is None

    @pytest.mark.unit
    def test_a_schema_2_row_keeps_the_empty_list_distinct(self) -> None:
        """At schema 2 the field means something, including when it is empty."""
        assert _to_entry(_row(schema_version=2, agent_session_ids=[])).agent_session_ids == []
        assert _to_entry(_row(schema_version=2, agent_session_ids=["x"])).agent_session_ids == ["x"]

    @pytest.mark.unit
    def test_unreported_agent_sessions_are_null_not_empty(self) -> None:
        """A verdict from an older exporter cannot answer the question.

        null says "not reported"; [] would claim the sweep confirmed none.
        """
        entry = _to_entry(_row())

        assert entry is not None
        assert entry.agent_session_ids is None

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


class TestTheDiagnosisTextIsNotExposed:
    """Withheld rather than sanitised, because sanitising it lost.

    The exporter interpolates the store URL into its reason, and that URL can
    carry the write token. A regex that redacted URLs out of the text was
    bypassed four ways - `//secret@host` missed entirely, `https://user:
    secret@host` redacted only the prefix and left the credential, a bare
    `token=...` untouched, and trailing punctuation eaten off the sentences it
    did match. Every fix would have been another guess about the boundaries of
    untrusted free text.
    """

    TOKEN = "super-secret-write-token"

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "reason",
        [
            "exporter reported success against 'https://{token}@host', not configured",
            "store unreachable at //{token}@example.com/path",
            "auth failed for https://user: {token}@example.com/path",
            "rejected with token={token}",
            "see https://example.com/{token}),",
        ],
    )
    def test_no_reason_text_reaches_the_response(self, reason: str) -> None:
        entry = _to_entry(_row(state="failed", reason=reason.format(token=self.TOKEN)))

        assert entry is not None
        # The field does not exist on the response at all, so there is no
        # sanitiser left to bypass.
        assert not hasattr(entry, "reason")
        assert self.TOKEN not in entry.model_dump_json()


class TestAContradictoryCapturedRowIsNotTrusted:
    """A stored row claiming success while counting losses contradicts itself.

    The current producer cannot emit it - capture_result refuses the same
    contradiction - but this read path must not TRUST that. A semantically
    impossible row is the one whose success claim is worth least.
    """

    @pytest.mark.unit
    @pytest.mark.parametrize("counter", ["rejected", "skipped_oversize", "failed", "unconfirmed"])
    def test_a_captured_row_counting_losses_is_downgraded(self, counter: str) -> None:
        entry = _to_entry(_row(state="captured", counters={counter: 1}))

        assert entry is not None
        assert entry.state == "unknown"
        assert entry.needs_backfill is True

    @pytest.mark.unit
    def test_a_clean_captured_row_stays_settled(self) -> None:
        """The guard must not condemn every success."""
        entry = _to_entry(_row(state="captured", counters={"discovered": 3, "sent": 3}))

        assert entry is not None
        assert entry.state == "captured"
        assert entry.needs_backfill is False
