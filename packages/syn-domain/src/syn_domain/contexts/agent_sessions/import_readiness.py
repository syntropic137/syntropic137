"""Deciding whether a phase's delegates can be imported YET (#895).

Capture lands AFTER an execution reports completed. Querying the store the
instant an execution completed returned zero sessions where seconds later it
held two. A reader that treats that emptiness as "nothing to import" reports
success having imported nothing, and the resulting undercount looks exactly
like a phase that never delegated.

So "the store does not have it" has two meanings, and this module is the one
place they are separated. It is a pure decision over values, deliberately not
a branch inside a processor, so the race can be asserted in a unit test
instead of reproduced against a live store.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.phase_reconciliation import (
        PhaseReconciliation,
    )


class ImportReadiness(StrEnum):
    """Whether this phase's delegate costs can be committed now."""

    READY = "ready"
    """Everything that is coming has arrived. Import and finalise."""

    WAIT = "wait"
    """Capture is still in flight. Ask again rather than finalising a phase at
    less than its true cost."""


def assess_import_readiness(
    reconciliation: PhaseReconciliation, accepted_count: int | None
) -> ImportReadiness:
    """Decide whether to import this phase's delegates or ask again later.

    Args:
        reconciliation: What the store could tell us about the phase's
            sessions right now.
        accepted_count: The capture observation's count of sessions it
            accepted for this phase, or None when the capture did not report
            one. This is the ONLY evidence separating "the transcript is on
            its way" from "it never arrived"; nothing else here can tell the
            two apart.
    """
    # A failed lookup is retried on its own terms. No capture counter can
    # retire it, because a call that never completed says nothing about how
    # many sessions exist - so counting must not be allowed to declare it
    # settled.
    if reconciliation.transient_delegate_ids:
        return ImportReadiness.WAIT

    absent = reconciliation.missing_delegate_ids
    if not absent:
        # Nothing outstanding. Delegates that are present-but-unreadable, and
        # sessions that are unattributable, are settled verdicts rather than
        # pending ones: re-reading the store will not change either, and
        # waiting on them would retry forever.
        return ImportReadiness.READY

    if accepted_count is None:
        # The evidence that would end the wait is unavailable. Err toward WAIT,
        # which keeps a retryable gap retryable, rather than toward finalising
        # it silently. Retries are bounded by the caller, so this cannot spin
        # indefinitely on its own.
        return ImportReadiness.WAIT

    # Capture promised a number of sessions. If the store has already produced
    # at least that many, nothing further is coming and the absent ones truly
    # never arrived: let the phase finalise carrying the gap rather than retry
    # until something gives up. A count below what we have seen is nonsensical
    # and gets the same treatment, since it cannot be describing more to come.
    # Counted against the LEADER too, because capture counts every session it
    # accepted without distinguishing which one led. Unattributable sessions
    # are not in this sum: a phase is either classified or refused whole, so
    # when there are absent delegates there are no unattributable ids beside
    # them.
    present_delegates = len(reconciliation.delegates) - len(absent)
    leader_present = 1 if reconciliation.leader_session_id is not None else 0
    accounted = present_delegates + leader_present
    return ImportReadiness.READY if accounted >= accepted_count else ImportReadiness.WAIT
