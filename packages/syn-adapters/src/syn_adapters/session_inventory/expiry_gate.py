"""Automatic body expiry only behind a confirmed remote copy (#2107).

Owner deletions and retractions are never gated: they express owner intent.
Age and quota expiry are, because the owner's rule is to keep every session and
let a body leave local disk only when the archive holds the same revision.

Only the newest, full revision of a transcript is ever eligible. Older
revisions are kept: after splice dedupe they are small references into the
newest, and they were never uploaded under their own hash (#2107 R1). The
caller decides eligibility; this gate then permits one expiry only when ALL
hold, checked right before deletion:

- the operator attested that the archive is itself backed up off-site, since a
  confirmation is a durable commit and not backup evidence (APSS draft s9);
- the archive answers ``RevisionConfirmed`` for every uploaded revision the
  body backs.

Any other answer keeps the bytes. It is logged and counted, never retried here.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions.ports.SessionArchiveSinkPort import (
    ArchiveUnavailable,
    ConfirmNotAdvertised,
    ConfirmUnauthorized,
    ConfirmUnexpectedResponse,
    RevisionAbsent,
    RevisionConfirmation,
    RevisionConfirmed,
    RevisionIntegrityFailure,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_domain.contexts.agent_sessions.ports.SessionArchiveSinkPort import (
        SessionArchiveSinkPort,
        UploadedRevision,
    )

logger = logging.getLogger(__name__)


class ExpiryHold(StrEnum):
    """Why an automatic expiry kept the bytes. Stored with the hold row."""

    NO_BACKUP_ATTESTATION = "no_backup_attestation"
    OLDER_REVISION = "older_revision"
    NOT_UPLOADED = "not_uploaded"
    SPLICE_BASE = "splice_base"
    ABSENT = "absent"
    UNAUTHORIZED = "unauthorized"
    INTEGRITY_FAILURE = "integrity_failure"
    UNAVAILABLE = "unavailable"
    NOT_ADVERTISED = "not_advertised"
    UNEXPECTED = "unexpected"


@dataclass(frozen=True, slots=True)
class ExpiryDecision:
    hold: ExpiryHold | None
    """None permits deletion; anything else keeps the bytes."""

    @property
    def permitted(self) -> bool:
        return self.hold is None


def _hold_for(outcome: RevisionConfirmation) -> ExpiryHold | None:
    match outcome:
        case RevisionConfirmed():
            return None
        case RevisionAbsent():
            return ExpiryHold.ABSENT
        case ConfirmUnauthorized():
            return ExpiryHold.UNAUTHORIZED
        case RevisionIntegrityFailure():
            return ExpiryHold.INTEGRITY_FAILURE
        case ArchiveUnavailable():
            return ExpiryHold.UNAVAILABLE
        case ConfirmNotAdvertised():
            return ExpiryHold.NOT_ADVERTISED
        case ConfirmUnexpectedResponse():
            return ExpiryHold.UNEXPECTED


class ConfirmedExpiryGate:
    def __init__(self, sink: SessionArchiveSinkPort, *, offsite_backup_attested: bool) -> None:
        self._sink = sink
        self._attested = offsite_backup_attested
        self.holds: Counter[ExpiryHold] = Counter()
        self.permitted = 0

    async def decide(
        self, revisions: Sequence[UploadedRevision], *, ineligible: ExpiryHold | None = None
    ) -> ExpiryDecision:
        """Decide one body's automatic expiry. Call immediately before deleting.

        ``ineligible`` is the caller's reason the body may not expire at all
        (an older revision, a newest one not yet uploaded, or a splice base); the archive is
        then not asked.
        """
        decision = await self._decide(revisions, ineligible)
        if decision.hold is None:
            self.permitted += 1
        else:
            self.holds[decision.hold] += 1
            logger.warning("Automatic body expiry held: %s", decision.hold.value)
        return decision

    async def _decide(
        self, revisions: Sequence[UploadedRevision], ineligible: ExpiryHold | None
    ) -> ExpiryDecision:
        if not self._attested:
            return ExpiryDecision(ExpiryHold.NO_BACKUP_ATTESTATION)
        if ineligible is not None:
            return ExpiryDecision(ineligible)
        if not revisions:
            return ExpiryDecision(ExpiryHold.NOT_UPLOADED)
        for revision in revisions:
            hold = _hold_for(await self._sink.confirm(revision))
            if hold is not None:
                return ExpiryDecision(hold)
        return ExpiryDecision(None)
