"""Ticket aggregate root: one problem, reported by one or more submissions (ADR-076-feedback-ticketing).

Holds ids and hashes only. Reporter text lives in the purgeable intake log and
never reaches the event store, so it can be erased and an injection string can
never reach a projection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from event_sourcing import AggregateRoot, aggregate, command_handler, event_sourcing_handler

from syn_domain.contexts.feedback._shared.value_objects import (
    FixObservation,
    PullRequestObservation,
    PullRequestState,
    Screening,
    TicketStatus,
    derive_status,
)
from syn_domain.contexts.feedback.domain.events import (
    TicketClosedEvent,
    TicketFixObservedEvent,
    TicketFixReleasedEvent,
    TicketLinkedToExecutionEvent,
    TicketLinkedToIssueEvent,
    TicketOpenedEvent,
    TicketPullRequestLinkedEvent,
    TicketPullRequestStateChangedEvent,
    TicketReleasedFromQuarantineEvent,
    TicketReopenedEvent,
    TicketReportAddedEvent,
    TicketReportDetachedEvent,
    TicketReprioritisedEvent,
    TicketResolvedEvent,
)
from syn_domain.contexts.feedback.domain.ResolutionPolicy import ResolutionPolicy

if TYPE_CHECKING:
    from syn_domain.contexts.feedback._shared.value_objects import Priority
    from syn_domain.contexts.feedback.domain.commands import (
        AddReportCommand,
        CloseTicketCommand,
        DetachReportCommand,
        LinkPullRequestCommand,
        LinkTicketToExecutionCommand,
        LinkTicketToIssueCommand,
        OpenTicketCommand,
        RecordFixObservationCommand,
        RecordFixReleaseCommand,
        RecordPullRequestStateCommand,
        ReleaseTicketFromQuarantineCommand,
        ReopenTicketCommand,
        ReprioritiseTicketCommand,
    )


@aggregate("Ticket")
class TicketAggregate(AggregateRoot["TicketOpenedEvent"]):
    """A ticket and every fact about its reports, its fix and its resolution.

    Retries are expected (the Screener re-runs after a crash), so the facts that
    a retry would repeat - opening, adding a member, linking a PR - are no-ops
    the second time rather than errors.
    """

    _aggregate_type: str

    def __init__(self) -> None:
        super().__init__()
        self._number: int | None = None
        self._opening_submission: str | None = None
        self._screening = Screening.CLEAN
        self._priority: Priority | None = None
        # submission_id -> source_id (None for the anonymous lane)
        self._members: dict[str, str | None] = {}
        self._pull_requests: dict[tuple[str, int], PullRequestObservation] = {}
        self._observations: dict[str, FixObservation] = {}
        self._released = False
        self._resolved = False
        self._resolved_version: str | None = None
        self._closed = False

    def get_aggregate_type(self) -> str:
        return self._aggregate_type

    # =========================================================================
    # PROPERTIES
    # =========================================================================

    @property
    def number(self) -> int | None:
        return self._number

    @property
    def reporter_count(self) -> int:
        """Submissions that are members of this ticket. Unique per submission."""
        return len(self._members)

    @property
    def screening(self) -> Screening:
        return self._screening

    @property
    def priority(self) -> Priority | None:
        return self._priority

    @property
    def status(self) -> TicketStatus:
        return derive_status(
            screening=self._screening,
            closed=self._closed,
            resolved=self._resolved,
            pull_requests=[pr.state for pr in self._pull_requests.values()],
        )

    @property
    def resolved_version(self) -> str | None:
        return self._resolved_version

    def fix_observation(self, source_id: str) -> FixObservation | None:
        """What this source last observed: drives "fixed in your deployment at <version>"."""
        return self._observations.get(source_id)

    # =========================================================================
    # COMMAND HANDLERS
    # =========================================================================

    @command_handler("OpenTicketCommand")
    def open_ticket(self, command: OpenTicketCommand) -> None:
        if self.id is not None and self._opening_submission != command.submission_id:
            msg = f"Ticket {self.id} was opened by a different submission"
            raise ValueError(msg)
        if self.id is not None:
            return  # a retry of the same open: no-op success
        self._initialize(command.aggregate_id)
        self._apply(
            TicketOpenedEvent(
                ticket_id=command.aggregate_id,
                number=command.number,
                submission_id=command.submission_id,
                content_hash=command.content_hash,
                source_id=command.source_id,
                provenance=command.provenance,
                screening=command.screening,
                type=command.type,
                priority=command.priority,
                confidence=command.confidence,
                recurrence_of=command.recurrence_of,
            )
        )

    @command_handler("AddReportCommand")
    def add_report(self, command: AddReportCommand) -> None:
        self._require_exists()
        if self._closed or self._resolved:
            msg = "Cannot add a report to a closed or resolved ticket; open a recurrence"
            raise ValueError(msg)
        if command.screening is Screening.QUARANTINED and self._screening is Screening.CLEAN:
            msg = "A quarantined submission never joins a clean ticket"
            raise ValueError(msg)
        if command.submission_id in self._members:
            return  # already a member: the reporter count must not rise twice
        self._apply(
            TicketReportAddedEvent(
                ticket_id=self._ticket_id,
                submission_id=command.submission_id,
                source_id=command.source_id,
                similarity=command.similarity,
            )
        )

    @command_handler("DetachReportCommand")
    def detach_report(self, command: DetachReportCommand) -> None:
        self._require_exists()
        if command.submission_id not in self._members:
            msg = f"Submission {command.submission_id} is not a report on this ticket"
            raise ValueError(msg)
        if len(self._members) == 1:
            msg = "Cannot detach a ticket's only report; close the ticket instead"
            raise ValueError(msg)
        self._apply(
            TicketReportDetachedEvent(
                ticket_id=self._ticket_id,
                submission_id=command.submission_id,
                by=command.by,
                reason=command.reason,
            )
        )

    @command_handler("ReleaseTicketFromQuarantineCommand")
    def release_from_quarantine(self, command: ReleaseTicketFromQuarantineCommand) -> None:
        self._require_exists()
        if self._screening is not Screening.QUARANTINED:
            msg = "Only a quarantined ticket can be released"
            raise ValueError(msg)
        self._apply(
            TicketReleasedFromQuarantineEvent(
                ticket_id=self._ticket_id, by=command.by, reason=command.reason
            )
        )

    @command_handler("ReprioritiseTicketCommand")
    def reprioritise(self, command: ReprioritiseTicketCommand) -> None:
        if self.id is None:
            msg = "Ticket does not exist"
            raise ValueError(msg)
        if command.priority is self._priority:
            return
        self._apply(
            TicketReprioritisedEvent(
                ticket_id=self._ticket_id, priority=command.priority, by=command.by
            )
        )

    @command_handler("LinkTicketToIssueCommand")
    def link_to_issue(self, command: LinkTicketToIssueCommand) -> None:
        self._require_exists()
        if self._screening is Screening.QUARANTINED:
            msg = "A quarantined ticket cannot be linked to an issue; release it first"
            raise ValueError(msg)
        self._apply(
            TicketLinkedToIssueEvent(
                ticket_id=self._ticket_id,
                repository=command.repository,
                repository_id=command.repository_id,
                number=command.number,
            )
        )

    @command_handler("LinkTicketToExecutionCommand")
    def link_to_execution(self, command: LinkTicketToExecutionCommand) -> None:
        self._require_exists()
        if self._screening is Screening.QUARANTINED:
            msg = "A quarantined ticket cannot be linked to an execution; release it first"
            raise ValueError(msg)
        self._apply(
            TicketLinkedToExecutionEvent(
                ticket_id=self._ticket_id, execution_id=command.execution_id
            )
        )

    @command_handler("LinkPullRequestCommand")
    def link_pull_request(self, command: LinkPullRequestCommand) -> None:
        self._require_exists()
        if self._screening is Screening.QUARANTINED:
            msg = "A quarantined ticket cannot be linked to a pull request; release it first"
            raise ValueError(msg)
        if (command.repository, command.number) in self._pull_requests:
            return
        self._apply(
            TicketPullRequestLinkedEvent(
                ticket_id=self._ticket_id,
                repository=command.repository,
                repository_id=command.repository_id,
                number=command.number,
            )
        )

    @command_handler("RecordPullRequestStateCommand")
    def record_pull_request_state(self, command: RecordPullRequestStateCommand) -> None:
        self._require_exists()
        current = self._pull_requests.get((command.repository, command.number))
        if current is None:
            msg = f"Pull request {command.repository}#{command.number} is not linked"
            raise ValueError(msg)
        if current.state is PullRequestState.MERGED:
            return  # merged is terminal
        if current.observed_at is not None and command.observed_at <= current.observed_at:
            return  # an older (or repeated) observation never overwrites a newer one
        self._apply(
            TicketPullRequestStateChangedEvent(
                ticket_id=self._ticket_id,
                repository=command.repository,
                number=command.number,
                state=command.state,
                merge_commit=command.merge_commit,
                observed_at=command.observed_at,
            )
        )

    @command_handler("RecordFixObservationCommand")
    def record_fix_observation(self, command: RecordFixObservationCommand) -> None:
        self._require_exists()
        if not self._has_merged_fix:
            msg = "No linked pull request has merged, so there is no fix to observe"
            raise ValueError(msg)
        previous = self._observations.get(command.source_id)
        if previous is not None and command.observed_at <= previous.observed_at:
            return  # per source, the latest observation wins
        self._apply(
            TicketFixObservedEvent(
                ticket_id=self._ticket_id,
                source_id=command.source_id,
                commit=command.commit,
                version=command.version,
                contains_fix=command.contains_fix,
                observed_at=command.observed_at,
            )
        )
        self._resolve_if_due(command.version)

    @command_handler("RecordFixReleaseCommand")
    def record_fix_release(self, command: RecordFixReleaseCommand) -> None:
        self._require_exists()
        if not self._has_merged_fix:
            msg = "No linked pull request has merged, so there is no fix to observe"
            raise ValueError(msg)
        if self._released:
            return
        self._apply(
            TicketFixReleasedEvent(
                ticket_id=self._ticket_id,
                release_tag=command.release_tag,
                version=command.version,
                commit=command.commit,
            )
        )
        self._resolve_if_due(command.version)

    @command_handler("CloseTicketCommand")
    def close(self, command: CloseTicketCommand) -> None:
        from syn_domain.contexts.feedback._shared.value_objects import CloseReason

        self._require_exists()
        if self._closed:
            msg = "Ticket is already closed"
            raise ValueError(msg)
        if (command.reason is CloseReason.DUPLICATE_OF) != (command.duplicate_of is not None):
            msg = "duplicate_of is required exactly when the reason is duplicate_of"
            raise ValueError(msg)
        self._apply(
            TicketClosedEvent(
                ticket_id=self._ticket_id,
                reason=command.reason,
                duplicate_of=command.duplicate_of,
            )
        )

    @command_handler("ReopenTicketCommand")
    def reopen(self, command: ReopenTicketCommand) -> None:
        self._require_exists()
        if not (self._closed or self._resolved):
            msg = "Only a closed or resolved ticket can be reopened"
            raise ValueError(msg)
        self._apply(
            TicketReopenedEvent(ticket_id=self._ticket_id, by=command.by, reason=command.reason)
        )

    # =========================================================================
    # GUARDS
    # =========================================================================

    @property
    def _ticket_id(self) -> str:
        return str(self.id)

    def _require_exists(self) -> None:
        if self.id is None:
            msg = "Ticket does not exist"
            raise ValueError(msg)

    @property
    def _has_merged_fix(self) -> bool:
        return any(pr.state is PullRequestState.MERGED for pr in self._pull_requests.values())

    def _resolve_if_due(self, version: str) -> None:
        """Emit TicketResolved in the same command whose event made the policy true."""
        if self._resolved:
            return
        rule = ResolutionPolicy.decide(
            released=self._released,
            signed_reporters={s for s in self._members.values() if s is not None},
            observations=self._observations,
        )
        if rule is None:
            return
        self._apply(TicketResolvedEvent(ticket_id=self._ticket_id, rule=rule, version=version))

    # =========================================================================
    # EVENT SOURCING HANDLERS
    # =========================================================================

    @event_sourcing_handler("TicketOpened")
    def on_opened(self, event: TicketOpenedEvent) -> None:
        self._number = event.number
        self._opening_submission = event.submission_id
        self._screening = event.screening
        self._priority = event.priority
        self._members = {event.submission_id: event.source_id}

    @event_sourcing_handler("TicketReportAdded")
    def on_report_added(self, event: TicketReportAddedEvent) -> None:
        self._members[event.submission_id] = event.source_id

    @event_sourcing_handler("TicketReportDetached")
    def on_report_detached(self, event: TicketReportDetachedEvent) -> None:
        self._members.pop(event.submission_id, None)

    @event_sourcing_handler("TicketReleasedFromQuarantine")
    def on_released_from_quarantine(self, _event: TicketReleasedFromQuarantineEvent) -> None:
        self._screening = Screening.CLEAN

    @event_sourcing_handler("TicketReprioritised")
    def on_reprioritised(self, event: TicketReprioritisedEvent) -> None:
        self._priority = event.priority

    @event_sourcing_handler("TicketLinkedToIssue")
    def on_linked_to_issue(self, _event: TicketLinkedToIssueEvent) -> None:
        """Read models hold the link; no decision here depends on it."""

    @event_sourcing_handler("TicketLinkedToExecution")
    def on_linked_to_execution(self, _event: TicketLinkedToExecutionEvent) -> None:
        """Read models hold the link; no decision here depends on it."""

    @event_sourcing_handler("TicketPullRequestLinked")
    def on_pull_request_linked(self, event: TicketPullRequestLinkedEvent) -> None:
        self._pull_requests[(event.repository, event.number)] = PullRequestObservation(
            state=PullRequestState.OPEN
        )

    @event_sourcing_handler("TicketPullRequestStateChanged")
    def on_pull_request_state_changed(self, event: TicketPullRequestStateChangedEvent) -> None:
        self._pull_requests[(event.repository, event.number)] = PullRequestObservation(
            state=event.state, observed_at=event.observed_at
        )

    @event_sourcing_handler("TicketFixObserved")
    def on_fix_observed(self, event: TicketFixObservedEvent) -> None:
        self._observations[event.source_id] = FixObservation(
            contains_fix=event.contains_fix,
            version=event.version,
            observed_at=event.observed_at,
        )

    @event_sourcing_handler("TicketFixReleased")
    def on_fix_released(self, _event: TicketFixReleasedEvent) -> None:
        self._released = True

    @event_sourcing_handler("TicketResolved")
    def on_resolved(self, event: TicketResolvedEvent) -> None:
        self._resolved = True
        self._resolved_version = event.version

    @event_sourcing_handler("TicketClosed")
    def on_closed(self, _event: TicketClosedEvent) -> None:
        self._closed = True

    @event_sourcing_handler("TicketReopened")
    def on_reopened(self, _event: TicketReopenedEvent) -> None:
        """A regression: the fix that resolved it did not hold, so its evidence goes too."""
        self._closed = False
        self._resolved = False
        self._resolved_version = None
        self._released = False
        self._observations = {}
