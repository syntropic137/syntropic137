"""Deciding whether a phase's delegates can be imported YET (#895).

Capture lands AFTER an execution reports completed. A reader arriving promptly
sees an empty store for sessions that appear seconds later, and the failure is
silent: it imports nothing and reports success. This module is the one place
that difference is decided, so the decision is a value that can be asserted
rather than a branch buried in a processor.

The captured session ids are the authority for what exists: capture CONFIRMED
them, so a delegate the store cannot yet return is late rather than absent.
What ends the wait is an explicit retry bound, not a counter.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.agent_sessions.import_readiness import (
    ImportReadiness,
    assess_import_readiness,
)
from syn_domain.contexts.agent_sessions.phase_reconciliation import (
    DelegateCost,
    PhaseReconciliation,
)
from syn_domain.contexts.agent_sessions.transcript_usage import (
    PricedUsage,
    RetryDisposition,
    UnpricedUsage,
)


def _priced(session_id: str) -> DelegateCost:
    return DelegateCost(
        session_id=session_id,
        usage=PricedUsage(
            model="claude-opus-4",
            uncached_input_tokens=1,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            output_tokens=10,
            message_count=1,
        ),
    )


def _absent(session_id: str) -> DelegateCost:
    return DelegateCost(
        session_id=session_id,
        usage=UnpricedUsage(
            f"no stored session for {session_id!r}", retry=RetryDisposition.MISSING
        ),
    )


def _unreadable(session_id: str) -> DelegateCost:
    return DelegateCost(session_id=session_id, usage=UnpricedUsage("transcript unreadable"))


def _phase(*delegates: DelegateCost, leader: str | None = "s-leader") -> PhaseReconciliation:
    return PhaseReconciliation(leader_session_id=leader, delegates=delegates, unattributable=())


@pytest.mark.unit
class TestTheRaceIsNotMistakenForCompletion:
    def test_a_missing_delegate_waits_while_budget_remains(self) -> None:
        """The silent failure this module exists to prevent.

        Capture confirmed the delegate, so the store not returning it yet
        means late, not absent. Finalising here reports the phase at less than
        its true cost, and the shortfall is invisible afterwards.
        """
        readiness = assess_import_readiness(
            reconciliation=_phase(_priced("s-a"), _absent("s-b")), attempts_remaining=3
        )

        assert readiness is ImportReadiness.WAIT

    def test_all_delegates_missing_waits(self) -> None:
        """The exact shape observed in practice: query the instant the
        execution completes and the store returns nothing at all.
        """
        readiness = assess_import_readiness(
            reconciliation=_phase(_absent("s-a")), attempts_remaining=3
        )

        assert readiness is ImportReadiness.WAIT

    def test_every_delegate_priced_is_ready(self) -> None:
        readiness = assess_import_readiness(
            reconciliation=_phase(_priced("s-a")), attempts_remaining=3
        )

        assert readiness is ImportReadiness.READY


@pytest.mark.unit
class TestWaitingDoesNotBecomeForever:
    """Retrying forever is its own bug, so the wait is bounded and exhaustion
    is a state a caller can act on.
    """

    def test_a_spent_budget_exhausts_rather_than_waiting(self) -> None:
        readiness = assess_import_readiness(
            reconciliation=_phase(_absent("s-a")), attempts_remaining=0
        )

        assert readiness is ImportReadiness.EXHAUSTED

    def test_a_negative_budget_exhausts(self) -> None:
        readiness = assess_import_readiness(
            reconciliation=_phase(_absent("s-a")), attempts_remaining=-1
        )

        assert readiness is ImportReadiness.EXHAUSTED

    def test_exhausted_is_not_ready(self) -> None:
        """The distinction an operator depends on. READY says this phase's
        cost is complete; EXHAUSTED says it is known to be short. Collapsing
        them turns a reported gap back into a silent one.
        """
        exhausted = assess_import_readiness(
            reconciliation=_phase(_absent("s-a")), attempts_remaining=0
        )
        complete = assess_import_readiness(
            reconciliation=_phase(_priced("s-a")), attempts_remaining=0
        )

        assert exhausted is not complete
        assert complete is ImportReadiness.READY

    def test_an_unreadable_delegate_never_waits(self) -> None:
        """Present but unparseable. Asking again cannot change the answer, so
        it must not hold the phase open however much budget remains.
        """
        readiness = assess_import_readiness(
            reconciliation=_phase(_unreadable("s-a")), attempts_remaining=99
        )

        assert readiness is ImportReadiness.READY


@pytest.mark.unit
class TestPhasesWithNothingToImport:
    def test_a_phase_that_delegated_nothing_is_ready(self) -> None:
        readiness = assess_import_readiness(reconciliation=_phase(), attempts_remaining=3)

        assert readiness is ImportReadiness.READY

    def test_an_unattributable_phase_is_ready_not_waiting(self) -> None:
        """Unattributable is a settled verdict, not a pending one. Waiting on
        it would retry a phase whose sessions cannot become classifiable by
        re-reading the store.
        """
        reconciliation = PhaseReconciliation(
            leader_session_id=None, delegates=(), unattributable=("s-a", "s-b")
        )

        readiness = assess_import_readiness(reconciliation=reconciliation, attempts_remaining=3)

        assert readiness is ImportReadiness.READY


@pytest.mark.unit
class TestATransientFailureIsTreatedLikeAMissingOne:
    """Both are recoverable and neither can be settled by counting, so both
    hold the phase open until the budget runs out.
    """

    def _transient(self, session_id: str) -> DelegateCost:
        return DelegateCost(
            session_id=session_id,
            usage=UnpricedUsage(
                "store lookup failed: connection reset",
                retry=RetryDisposition.TRANSIENT,
            ),
        )

    def test_a_failed_lookup_waits(self) -> None:
        readiness = assess_import_readiness(
            reconciliation=_phase(_priced("s-a"), self._transient("s-b")),
            attempts_remaining=3,
        )

        assert readiness is ImportReadiness.WAIT

    def test_a_failed_lookup_exhausts_rather_than_spinning(self) -> None:
        """A deterministic adapter error looks transient from here and would
        otherwise retry forever. The bound is what makes classifying broadly
        safe: a misjudged error costs a few attempts, then a visible gap.
        """
        readiness = assess_import_readiness(
            reconciliation=_phase(self._transient("s-a")), attempts_remaining=0
        )

        assert readiness is ImportReadiness.EXHAUSTED
