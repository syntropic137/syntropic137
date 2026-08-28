"""Deciding whether a phase's delegates can be imported YET (#895).

Capture lands AFTER an execution reports completed. A reader arriving promptly
sees an empty store for sessions that appear seconds later, and the failure is
silent: it imports nothing and reports success. This module is the one place
that difference is decided, so the decision is a value that can be asserted
rather than a branch buried in a processor.

The capture observation's ``accepted`` counter is the only evidence available
that separates "not yet" from "never arrived".
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
    def test_an_absent_delegate_with_capture_still_pending_says_wait(self) -> None:
        """The silent failure this module exists to prevent.

        The phase has three sessions: a leader and two delegates, which is
        what capture accepted. The store has produced two of them. The third
        is in flight, not missing, and importing now would finalise the phase
        below its true cost.

        The count includes the LEADER, because capture counts every session it
        accepted and does not distinguish which one led.
        """
        readiness = assess_import_readiness(
            reconciliation=_phase(_priced("s-a"), _absent("s-b")), accepted_count=3
        )

        assert readiness is ImportReadiness.WAIT

    def test_all_delegates_absent_says_wait_not_nothing_to_do(self) -> None:
        """The exact shape observed in practice: query the instant the
        execution completes and the store returns zero sessions.
        """
        readiness = assess_import_readiness(reconciliation=_phase(_absent("s-a")), accepted_count=2)

        assert readiness is ImportReadiness.WAIT

    def test_every_delegate_priced_says_ready(self) -> None:
        readiness = assess_import_readiness(reconciliation=_phase(_priced("s-a")), accepted_count=2)

        assert readiness is ImportReadiness.READY


@pytest.mark.unit
class TestWaitingDoesNotBecomeForever:
    def test_an_absent_delegate_the_capture_never_promised_says_ready(self) -> None:
        """Retrying forever is its own bug.

        Capture accepted 1 session, the leader's, so nothing further is
        coming. The absent delegate genuinely never arrived, and the phase
        must be allowed to finalise carrying that gap rather than retry until
        something gives up.
        """
        readiness = assess_import_readiness(reconciliation=_phase(_absent("s-a")), accepted_count=1)

        assert readiness is ImportReadiness.READY

    def test_an_unreadable_delegate_never_waits(self) -> None:
        """Present but unparseable. Asking again cannot change the answer, so
        this must not be confused with the race no matter what the counter
        says.
        """
        readiness = assess_import_readiness(
            reconciliation=_phase(_unreadable("s-a")), accepted_count=5
        )

        assert readiness is ImportReadiness.READY


@pytest.mark.unit
class TestPhasesWithNothingToImport:
    def test_a_phase_that_delegated_nothing_is_ready(self) -> None:
        readiness = assess_import_readiness(reconciliation=_phase(), accepted_count=1)

        assert readiness is ImportReadiness.READY

    def test_an_unattributable_phase_is_ready_not_waiting(self) -> None:
        """Unattributable is a settled verdict, not a pending one. Waiting on
        it would retry a phase whose sessions will never become classifiable
        by re-reading the store.
        """
        reconciliation = PhaseReconciliation(
            leader_session_id=None, delegates=(), unattributable=("s-a", "s-b")
        )

        readiness = assess_import_readiness(reconciliation=reconciliation, accepted_count=2)

        assert readiness is ImportReadiness.READY


@pytest.mark.unit
class TestTheCounterIsTreatedAsUntrusted:
    def test_a_missing_counter_still_waits_on_an_absent_delegate(self) -> None:
        """When the capture reports no count, the evidence that would end the
        wait is unavailable. Erring toward WAIT keeps a retryable gap
        retryable; erring toward READY would finalise it silently, and the
        caller bounds retries anyway.
        """
        readiness = assess_import_readiness(
            reconciliation=_phase(_absent("s-a")), accepted_count=None
        )

        assert readiness is ImportReadiness.WAIT

    def test_a_nonsensical_counter_does_not_wait_forever(self) -> None:
        """A count below what the store already produced cannot be describing
        more sessions to come.
        """
        readiness = assess_import_readiness(
            reconciliation=_phase(_priced("s-a"), _absent("s-b")), accepted_count=0
        )

        assert readiness is ImportReadiness.READY


@pytest.mark.unit
class TestATransientFailureIsNotRetiredByCounting:
    """A failed lookup and an empty answer are both retryable, but they end
    for different reasons, and only one of them can be counted away.
    """

    def _transient(self, session_id: str) -> DelegateCost:
        return DelegateCost(
            session_id=session_id,
            usage=UnpricedUsage(
                "store lookup failed: connection reset",
                retry=RetryDisposition.TRANSIENT,
            ),
        )

    def test_a_failed_lookup_waits_even_when_the_count_is_satisfied(self) -> None:
        """The distinction that makes three states necessary rather than two.

        Capture accepted 2 and the store has produced 2, so a MISSING delegate
        here would correctly be counted away and finalised. But this delegate
        is not missing - the call never completed, and a call that never
        completed says nothing about how many sessions exist. Counting must
        not be allowed to declare it settled, or a reset connection silently
        costs a real delegate its price.
        """
        readiness = assess_import_readiness(
            reconciliation=_phase(_priced("s-a"), self._transient("s-b")),
            accepted_count=2,
        )

        assert readiness is ImportReadiness.WAIT

    def test_a_failed_lookup_waits_with_no_count_at_all(self) -> None:
        readiness = assess_import_readiness(
            reconciliation=_phase(self._transient("s-a")), accepted_count=None
        )

        assert readiness is ImportReadiness.WAIT
