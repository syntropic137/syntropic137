"""Feedback bounded context - tickets built from screened user feedback (ADR-076).

Public API for cross-context consumers (ADR-062). Reporter text never enters
this context's events: they carry submission ids and content hashes only.

Usage:
    from syn_domain.contexts.feedback import OpenTicketCommand, TicketAggregate

    ticket = TicketAggregate()
    ticket.open_ticket(OpenTicketCommand(aggregate_id=ticket_id, ...))
"""

from syn_domain.contexts.feedback._shared import (
    CloseReason,
    FixObservation,
    Priority,
    Provenance,
    PullRequestRef,
    PullRequestState,
    ResolutionRule,
    Screening,
    TicketStatus,
    TicketType,
    derive_status,
)
from syn_domain.contexts.feedback.domain.aggregate_ticket import TicketAggregate
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
from syn_domain.contexts.feedback.domain.NearDuplicateMatcher import (
    MatchBucket,
    MatchCandidate,
    NearDuplicateMatch,
    NearDuplicateMatcher,
)
from syn_domain.contexts.feedback.domain.ResolutionPolicy import ResolutionPolicy
from syn_domain.contexts.feedback.domain.ScreenedText import MAX_SCREENED_CHARS, ScreenedText
from syn_domain.contexts.feedback.domain.ScreeningPolicy import (
    ScreeningDecision,
    ScreeningPolicy,
    ScreeningResult,
    ScreeningThresholds,
    ScreeningVerdict,
)
from syn_domain.contexts.feedback.ports import (
    Disposition,
    ForgeReads,
    IntakeLog,
    LeasedSubmission,
    NonceLedger,
    PublishedRelease,
    PullRequestSnapshot,
    RateBuckets,
    ScreeningPort,
)

__all__ = [
    "MAX_SCREENED_CHARS",
    "AddReportCommand",
    "CloseReason",
    "CloseTicketCommand",
    "DetachReportCommand",
    "Disposition",
    "FixObservation",
    "ForgeReads",
    "IntakeLog",
    "LeasedSubmission",
    "LinkPullRequestCommand",
    "LinkTicketToExecutionCommand",
    "LinkTicketToIssueCommand",
    "MatchBucket",
    "MatchCandidate",
    "NearDuplicateMatch",
    "NearDuplicateMatcher",
    "NonceLedger",
    "OpenTicketCommand",
    "Priority",
    "Provenance",
    "PublishedRelease",
    "PullRequestRef",
    "PullRequestSnapshot",
    "PullRequestState",
    "RateBuckets",
    "RecordFixObservationCommand",
    "RecordFixReleaseCommand",
    "RecordPullRequestStateCommand",
    "ReleaseTicketFromQuarantineCommand",
    "ReopenTicketCommand",
    "ReprioritiseTicketCommand",
    "ResolutionPolicy",
    "ResolutionRule",
    "ScreenedText",
    "Screening",
    "ScreeningDecision",
    "ScreeningPolicy",
    "ScreeningPort",
    "ScreeningResult",
    "ScreeningThresholds",
    "ScreeningVerdict",
    "TicketAggregate",
    "TicketClosedEvent",
    "TicketFixObservedEvent",
    "TicketFixReleasedEvent",
    "TicketLinkedToExecutionEvent",
    "TicketLinkedToIssueEvent",
    "TicketOpenedEvent",
    "TicketPullRequestLinkedEvent",
    "TicketPullRequestStateChangedEvent",
    "TicketReleasedFromQuarantineEvent",
    "TicketReopenedEvent",
    "TicketReportAddedEvent",
    "TicketReportDetachedEvent",
    "TicketReprioritisedEvent",
    "TicketResolvedEvent",
    "TicketStatus",
    "TicketType",
    "derive_status",
]
