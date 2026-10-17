"""Ticket aggregate: the PR 1 acceptance rows of the feedback plan (#1970, #2010).

Every scenario is asserted on a ticket REPLAYED from the events the commands
emitted, not on the instance that ran them: the guards must hold for a ticket
the Screener loads from the event store after a crash, which is the only kind
it ever sees.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.feedback import (
    AddReportCommand,
    CloseReason,
    CloseTicketCommand,
    DetachReportCommand,
    LinkPullRequestCommand,
    LinkTicketToExecutionCommand,
    LinkTicketToIssueCommand,
    OpenTicketCommand,
    Priority,
    Provenance,
    PullRequestState,
    RecordFixObservationCommand,
    RecordFixReleaseCommand,
    RecordPullRequestStateCommand,
    ReleaseTicketFromQuarantineCommand,
    ReopenTicketCommand,
    ResolutionRule,
    ScreenedText,
    Screening,
    TicketAggregate,
    TicketOpenedEvent,
    TicketReportAddedEvent,
    TicketReportDetachedEvent,
    TicketResolvedEvent,
    TicketStatus,
    TicketType,
)

if TYPE_CHECKING:
    from event_sourcing import DomainEvent, EventEnvelope
    from pydantic import BaseModel

pytestmark = pytest.mark.unit

TICKET = "0192a3b4-0000-7000-8000-000000000001"
T0 = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
REPO = "syntropic137/syntropic137"


class _Stream:
    """A ticket's event stream, reloaded before every command as the Screener would."""

    def __init__(self) -> None:
        self.history: list[EventEnvelope[DomainEvent]] = []

    def load(self) -> TicketAggregate:
        ticket = TicketAggregate()
        if self.history:
            ticket.rehydrate(self.history)
        return ticket

    @property
    def events(self) -> list[DomainEvent]:
        return [envelope.event for envelope in self.history]


def _run(stream: _Stream | None, *commands: BaseModel) -> _Stream:
    """Run each command against a ticket freshly loaded from the stream so far."""
    stream = stream or _Stream()
    for command in commands:
        ticket = stream.load()
        ticket._handle_command(command)  # ESP's own dispatch, by command class name
        stream.history.extend(ticket.get_uncommitted_events())
    return stream


def _open(
    *, source_id: str | None = "src-a", screening: Screening = Screening.CLEAN
) -> OpenTicketCommand:
    return OpenTicketCommand(
        aggregate_id=TICKET,
        number=12,
        submission_id="sub-1",
        content_hash=ScreenedText.screen("the save button does nothing").content_hash,
        source_id=source_id,
        provenance=Provenance(key_id="key-a" if source_id else None, surface="syn-ui"),
        screening=screening,
        type=TicketType.BUG,
        priority=Priority.P2,
        confidence=0.9,
    )


def _report(
    submission_id: str, source_id: str | None = "src-b", *, quarantined: bool = False
) -> AddReportCommand:
    return AddReportCommand(
        aggregate_id=TICKET,
        submission_id=submission_id,
        source_id=source_id,
        similarity=0.8,
        screening=Screening.QUARANTINED if quarantined else Screening.CLEAN,
    )


def _link(number: int) -> LinkPullRequestCommand:
    return LinkPullRequestCommand(
        aggregate_id=TICKET, repository=REPO, repository_id=1, number=number
    )


def _pr(number: int, state: PullRequestState, at: datetime) -> RecordPullRequestStateCommand:
    return RecordPullRequestStateCommand(
        aggregate_id=TICKET, repository=REPO, number=number, state=state, observed_at=at
    )


def _observe(
    source_id: str, at: datetime, *, contains_fix: bool = True, version: str = "0.30.0-beta.1"
) -> RecordFixObservationCommand:
    return RecordFixObservationCommand(
        aggregate_id=TICKET,
        source_id=source_id,
        commit="abc123",
        version=version,
        contains_fix=contains_fix,
        observed_at=at,
    )


def _merged() -> tuple[LinkPullRequestCommand, RecordPullRequestStateCommand]:
    return _link(40), _pr(40, PullRequestState.MERGED, T0)


def _counted_reporters(stream: _Stream) -> int:
    """The reporter count as a projection folds it: one per open or added report, less detaches.

    A read model counts events; it cannot see the aggregate's member set. So a
    duplicate ``TicketReportAdded`` that the aggregate would absorb on replay is
    still a wrong count everywhere the count is shown.
    """
    count = 0
    for event in stream.events:
        if isinstance(event, (TicketOpenedEvent, TicketReportAddedEvent)):
            count += 1
        elif isinstance(event, TicketReportDetachedEvent):
            count -= 1
    return count


def _resolved_events(stream: _Stream) -> list[TicketResolvedEvent]:
    return [e for e in stream.events if isinstance(e, TicketResolvedEvent)]


class TestQuarantine:
    def test_linking_a_quarantined_ticket_raises(self) -> None:
        ticket = _run(None, _open(screening=Screening.QUARANTINED))
        with pytest.raises(ValueError, match="quarantined"):
            _run(
                ticket,
                LinkTicketToIssueCommand(
                    aggregate_id=TICKET, repository=REPO, repository_id=1, number=5
                ),
            )
        with pytest.raises(ValueError, match="quarantined"):
            _run(ticket, LinkTicketToExecutionCommand(aggregate_id=TICKET, execution_id="exec-1"))
        with pytest.raises(ValueError, match="quarantined"):
            _run(ticket, _link(40))

    def test_released_ticket_can_be_linked(self) -> None:
        ticket = _run(
            None,
            _open(screening=Screening.QUARANTINED),
            ReleaseTicketFromQuarantineCommand(aggregate_id=TICKET, by="owner", reason="benign"),
            _link(40),
        )
        assert ticket.load().status is TicketStatus.IN_PROGRESS

    def test_quarantined_report_into_a_clean_ticket_raises(self) -> None:
        ticket = _run(None, _open())
        with pytest.raises(ValueError, match="never joins a clean ticket"):
            _run(ticket, _report("sub-2", quarantined=True))


class TestMembership:
    def test_the_same_report_twice_counts_once(self) -> None:
        ticket = _run(None, _open(), _report("sub-2"), _report("sub-2"))
        assert _counted_reporters(ticket) == 2
        assert ticket.load().reporter_count == 2

    def test_a_second_open_with_the_same_id_is_a_no_op(self) -> None:
        ticket = _run(None, _open(), _open())
        opened = [e for e in ticket.events if isinstance(e, TicketOpenedEvent)]
        assert len(opened) == 1
        assert ticket.load().reporter_count == 1

    def test_a_different_submission_cannot_reuse_the_ticket_id(self) -> None:
        ticket = _run(None, _open())
        clash = _open().model_copy(update={"submission_id": "sub-other"})
        with pytest.raises(ValueError, match="different submission"):
            _run(ticket, clash)

    def test_detach_drops_the_count(self) -> None:
        ticket = _run(
            None,
            _open(),
            _report("sub-2"),
            DetachReportCommand(
                aggregate_id=TICKET, submission_id="sub-2", by="owner", reason="over-merge"
            ),
        )
        assert _counted_reporters(ticket) == 1
        assert ticket.load().reporter_count == 1

    def test_a_closed_ticket_refuses_reports(self) -> None:
        ticket = _run(
            None, _open(), CloseTicketCommand(aggregate_id=TICKET, reason=CloseReason.INVALID)
        )
        with pytest.raises(ValueError, match="closed or resolved"):
            _run(ticket, _report("sub-2"))

    @pytest.mark.parametrize(
        "terminal",
        [
            CloseTicketCommand(aggregate_id=TICKET, reason=CloseReason.INVALID),
            _observe("src-a", T0),
        ],
        ids=["closed", "resolved"],
    )
    def test_a_retried_report_after_close_or_resolution_is_a_no_op(
        self, terminal: BaseModel
    ) -> None:
        ticket = _run(None, _open(source_id="src-a"), _report("sub-2", "src-a"), *_merged())
        ticket = _run(ticket, terminal)
        before = len(ticket.events)
        ticket = _run(ticket, _report("sub-2", "src-a"))
        assert len(ticket.events) == before
        assert _counted_reporters(ticket) == 2

    def test_a_retried_quarantined_report_after_release_is_a_no_op(self) -> None:
        ticket = _run(
            None,
            _open(screening=Screening.QUARANTINED),
            _report("sub-2", quarantined=True),
            ReleaseTicketFromQuarantineCommand(aggregate_id=TICKET, by="owner", reason="benign"),
        )
        before = len(ticket.events)
        ticket = _run(ticket, _report("sub-2", quarantined=True))
        assert len(ticket.events) == before
        assert _counted_reporters(ticket) == 2

    def test_a_new_quarantined_report_after_release_still_raises(self) -> None:
        ticket = _run(
            None,
            _open(screening=Screening.QUARANTINED),
            ReleaseTicketFromQuarantineCommand(aggregate_id=TICKET, by="owner", reason="benign"),
        )
        with pytest.raises(ValueError, match="never joins a clean ticket"):
            _run(ticket, _report("sub-3", quarantined=True))


class TestPullRequestStatus:
    def test_closed_then_reopened_is_in_progress_not_fix_merged(self) -> None:
        ticket = _run(
            None,
            _open(),
            _link(40),
            _pr(40, PullRequestState.CLOSED, T0),
            _pr(40, PullRequestState.OPEN, T0 + timedelta(minutes=5)),
        )
        assert ticket.load().status is TicketStatus.IN_PROGRESS

    def test_one_merged_and_one_open_is_in_progress(self) -> None:
        ticket = _run(
            None,
            _open(),
            _link(40),
            _link(41),
            _pr(40, PullRequestState.MERGED, T0),
            _pr(41, PullRequestState.OPEN, T0),
        )
        assert ticket.load().status is TicketStatus.IN_PROGRESS

    def test_merged_alone_is_fix_merged(self) -> None:
        ticket = _run(None, _open(), *_merged())
        assert ticket.load().status is TicketStatus.FIX_MERGED

    def test_an_older_state_change_is_ignored(self) -> None:
        ticket = _run(
            None,
            _open(),
            _link(40),
            _pr(40, PullRequestState.OPEN, T0 + timedelta(minutes=10)),
            _pr(40, PullRequestState.CLOSED, T0),
        )
        assert ticket.load().status is TicketStatus.IN_PROGRESS

    def test_merged_is_terminal(self) -> None:
        ticket = _run(
            None, _open(), *_merged(), _pr(40, PullRequestState.CLOSED, T0 + timedelta(hours=1))
        )
        assert ticket.load().status is TicketStatus.FIX_MERGED

    def test_state_of_an_unlinked_pr_raises(self) -> None:
        ticket = _run(None, _open())
        with pytest.raises(ValueError, match="not linked"):
            _run(ticket, _pr(99, PullRequestState.OPEN, T0))


class TestResolution:
    def _two_signed_sources(self) -> _Stream:
        return _run(None, _open(source_id="src-a"), _report("sub-2", "src-b"), *_merged())

    def test_one_of_two_signed_sources_does_not_resolve(self) -> None:
        ticket = _run(self._two_signed_sources(), _observe("src-a", T0))
        assert ticket.load().status is TicketStatus.FIX_MERGED
        assert _resolved_events(ticket) == []

    def test_both_signed_sources_resolve(self) -> None:
        ticket = _run(
            self._two_signed_sources(),
            _observe("src-a", T0, version="0.30.0-beta.1"),
            _observe("src-b", T0, version="0.30.0-beta.2"),
        )
        assert ticket.load().status is TicketStatus.RESOLVED
        [resolved] = _resolved_events(ticket)
        assert resolved.rule is ResolutionRule.ALL_REPORTERS_OBSERVED
        assert resolved.version == "0.30.0-beta.2"
        assert ticket.load().resolved_version == "0.30.0-beta.2"

    def test_an_older_out_of_order_observation_does_not_unresolve(self) -> None:
        ticket = _run(
            self._two_signed_sources(),
            _observe("src-a", T0 + timedelta(hours=1)),
            _observe("src-b", T0 + timedelta(hours=1)),
            _observe("src-a", T0, contains_fix=False),
        )
        assert ticket.load().status is TicketStatus.RESOLVED
        observation = ticket.load().fix_observation("src-a")
        assert observation is not None and observation.contains_fix

    def test_detaching_the_unobserved_reporter_resolves_in_the_same_command(self) -> None:
        ticket = _run(
            None,
            _open(source_id="src-a"),
            _report("sub-2", "src-b"),
            _report("sub-3", "src-c"),
            *_merged(),
            _observe("src-c", T0 + timedelta(hours=1), version="0.30.0-beta.2"),
            _observe("src-a", T0, version="0.30.0-beta.1"),
        )
        before = len(ticket.events)
        ticket = _run(
            ticket,
            DetachReportCommand(
                aggregate_id=TICKET, submission_id="sub-2", by="owner", reason="over-merge"
            ),
        )
        detached, resolved = ticket.events[before:]
        assert isinstance(detached, TicketReportDetachedEvent)
        assert isinstance(resolved, TicketResolvedEvent)
        assert resolved.rule is ResolutionRule.ALL_REPORTERS_OBSERVED
        assert resolved.version == "0.30.0-beta.2"  # the latest qualifying observation
        assert ticket.load().status is TicketStatus.RESOLVED

    def test_detaching_with_no_remaining_observation_does_not_resolve(self) -> None:
        ticket = _run(
            None,
            _open(source_id="src-a"),
            _report("sub-2", "src-b"),
            *_merged(),
            _observe("src-b", T0),
            DetachReportCommand(
                aggregate_id=TICKET, submission_id="sub-2", by="owner", reason="over-merge"
            ),
        )
        assert _resolved_events(ticket) == []
        assert ticket.load().status is TicketStatus.FIX_MERGED

    def test_anonymous_and_signed_resolve_on_release(self) -> None:
        ticket = _run(
            None,
            _open(source_id=None),
            _report("sub-2", "src-b"),
            *_merged(),
            RecordFixReleaseCommand(
                aggregate_id=TICKET, release_tag="v0.30.0", version="0.30.0", commit="def456"
            ),
        )
        assert ticket.load().status is TicketStatus.RESOLVED
        [resolved] = _resolved_events(ticket)
        assert resolved.rule is ResolutionRule.RELEASED
        assert resolved.version == "0.30.0"

    def test_an_anonymous_only_ticket_never_resolves_by_observation(self) -> None:
        ticket = _run(None, _open(source_id=None), *_merged(), _observe("src-z", T0))
        assert ticket.load().status is TicketStatus.FIX_MERGED

    def test_an_observation_needs_a_merged_pr(self) -> None:
        ticket = _run(None, _open(), _link(40))
        with pytest.raises(ValueError, match="merged"):
            _run(ticket, _observe("src-a", T0))

    def test_reopen_after_resolution_needs_new_evidence(self) -> None:
        ticket = _run(
            None,
            _open(source_id="src-a"),
            *_merged(),
            _observe("src-a", T0),
            ReopenTicketCommand(aggregate_id=TICKET, by="owner", reason="regressed"),
        )
        assert ticket.load().status is TicketStatus.FIX_MERGED
        assert ticket.load().resolved_version is None


def test_no_ticket_event_carries_reporter_text() -> None:
    """Hashes and ids only: the text of a submission is nowhere in the stream."""
    secret_text = "the save button does nothing"
    ticket = _run(None, _open(), _report("sub-2"), *_merged(), _observe("src-a", T0))
    for event in ticket.events:
        assert secret_text not in event.model_dump_json()
