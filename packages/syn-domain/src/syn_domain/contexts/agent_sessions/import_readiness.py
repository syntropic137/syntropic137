"""Deciding whether a phase's delegates can be imported YET (#895).

Capture lands AFTER an execution reports completed. Querying the store the
instant an execution completed returned zero sessions where seconds later it
held two. A reader that treats that emptiness as "nothing to import" reports
success having imported nothing, and the resulting undercount looks exactly
like a phase that never delegated.

So "the store does not have it" has two meanings, and this module separates
them. It is a pure decision over values, deliberately not a branch inside a
processor, so the race can be asserted in a unit test rather than reproduced
against a live store.

WHY THIS DOES NOT COUNT CAPTURE'S ``accepted`` COUNTER. An earlier version
compared what the store had produced against that counter and treated it as a
promised total. It is the exporter's tally, reported beside separate tallies
for discovered, uploaded, failed and rejected, and it is not a count of
distinct sessions - so reading it as one is wrong in BOTH directions. It can
finalise a phase whose delegate is still becoming readable, and it can wait
for a total that the set of distinct sessions will never reach.

The captured session ids are the authority instead, and they are already in
hand. Capture CONFIRMED those sessions, so a delegate the store cannot yet
return is late rather than absent, and only an explicit bound should end that
wait.
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
    """Nothing is outstanding. Import and finalise."""

    WAIT = "wait"
    """Capture is still landing, and budget to wait for it remains.

    NOT advisory. A caller must not emit the phase's cost while this stands:
    doing so finalises a number it already knows is short, and the shortfall
    is invisible afterwards.
    """

    EXHAUSTED = "exhausted"
    """Still outstanding, but the retry budget is spent.

    Finalise carrying a VISIBLE gap rather than retrying forever. Distinct
    from READY because the two mean opposite things to an operator: READY says
    this phase's cost is complete, EXHAUSTED says it is known to be short and
    names which sessions are missing.
    """


def assess_import_readiness(
    reconciliation: PhaseReconciliation, attempts_remaining: int
) -> ImportReadiness:
    """Decide whether to import this phase's delegates, wait, or give up.

    Args:
        reconciliation: What the store could tell us about the phase's
            sessions right now.
        attempts_remaining: How many further attempts the caller is willing to
            make. Zero or fewer means this is the last word.

    Returns:
        READY when nothing is outstanding, WAIT while something recoverable
        is, and EXHAUSTED when something is still outstanding but the budget
        is gone.
    """
    # Present-but-unreadable delegates and unattributable sessions are settled
    # verdicts, not pending ones: re-reading the store cannot change either,
    # so they never hold a phase open however much budget remains.
    outstanding = reconciliation.missing_delegate_ids + reconciliation.transient_delegate_ids
    if not outstanding:
        return ImportReadiness.READY

    # Both outstanding kinds are recoverable and neither can be resolved by
    # counting. A MISSING delegate was CONFIRMED by capture, so it is late
    # rather than absent. A TRANSIENT one never got an answer at all, and a
    # call that did not complete says nothing about what exists. The bound is
    # what ends either, and it is the caller's to spend.
    if attempts_remaining > 0:
        return ImportReadiness.WAIT

    return ImportReadiness.EXHAUSTED
