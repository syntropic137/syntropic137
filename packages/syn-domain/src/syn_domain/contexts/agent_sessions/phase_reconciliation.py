"""Turning one phase's capture into priced delegate usage (#895).

The composition step between "which harness sessions did this phase produce"
and "what did the ones nobody billed cost". It classifies the phase's captured
sessions, then prices ONLY those that are not already priced.

Two properties are worth stating because they are the reason this is a module
rather than a loop at the call site:

The leader is never fetched. Its tokens already exist as token_usage rows
under its platform session, so pricing it again inflates the execution total.
Not looking it up is a stronger guarantee than looking it up and discarding
the answer, because there is then no code path on which its number can reach a
total at all.

Nothing is dropped. Every captured id comes back as the leader, a delegate, or
unattributable. A dropped session is indistinguishable from a phase that never
delegated, which turns unpriced work into invisible work.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions.delegate_attribution import (
    SessionRole,
    classify_phase_sessions,
)
from syn_domain.contexts.agent_sessions.delegate_usage import resolve_delegate_usage
from syn_domain.contexts.agent_sessions.transcript_usage import (
    RetryDisposition,
    UnpricedUsage,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_domain.contexts.agent_sessions.delegate_usage import SessionStorePort
    from syn_domain.contexts.agent_sessions.transcript_usage import UsageResult


@dataclass(frozen=True)
class DelegateCost:
    """One delegated session and whatever could be recovered about its cost.

    ``usage`` is a result type, not a number, so an unpriceable delegate stays
    in the list carrying its reason instead of being filtered out.
    """

    session_id: str
    usage: UsageResult


@dataclass(frozen=True)
class PhaseReconciliation:
    """What one phase's captured sessions turned out to be."""

    leader_session_id: str | None
    """The session already priced, or None when it could not be identified."""

    delegates: tuple[DelegateCost, ...]
    """Sessions nobody billed. The thing this issue exists to recover."""

    unattributable: tuple[str, ...]
    """Captured, but not shown to be leader or delegate.

    Reported rather than priced: an operator can see there is unpriced work
    here and chase it, which is not true of a session that was silently
    dropped.
    """

    def _delegates_with(self, disposition: RetryDisposition) -> tuple[str, ...]:
        return tuple(
            delegate.session_id
            for delegate in self.delegates
            if isinstance(delegate.usage, UnpricedUsage) and delegate.usage.retry is disposition
        )

    @property
    def transient_delegate_ids(self) -> tuple[str, ...]:
        """Delegates whose lookup FAILED rather than came back empty.

        Kept apart from the missing ones because no capture counter can
        retire these: a reset connection says nothing about how many sessions
        exist, so counting cannot decide when to stop retrying them.
        """
        return self._delegates_with(RetryDisposition.TRANSIENT)

    @property
    def missing_delegate_ids(self) -> tuple[str, ...]:
        """Delegates the store did not have, which may simply be TOO EARLY.

        The store answered, and said it does not have them. Capture lands
        after an execution reports completed, so a reader arriving promptly
        sees exactly this for sessions that appear seconds later. A non-empty
        value means "ask again", not "nothing to do"; a caller that finalises
        on it turns the race into a silent undercount.

        Capture CONFIRMED these sessions, so one the store cannot return yet
        is late rather than absent. What ends the wait is an explicit retry
        bound, not a counter - see ``assess_import_readiness``.
        """
        return self._delegates_with(RetryDisposition.MISSING)


async def reconcile_phase_delegates(
    store: SessionStorePort,
    phase_provider: str,
    sessions: Sequence[tuple[str, str]],
) -> PhaseReconciliation:
    """Price the sessions of one phase that are not already priced.

    Args:
        store: Where delegated transcripts are read back from.
        phase_provider: The provider the phase DECLARED, whose session the
            platform already created and already priced.
        sessions: The ``(session_id, agent)`` pairs the capture reported.
    """
    # Order carries no meaning and must not be read as if it did. On real
    # capture the DELEGATE comes first: a codex-led phase reports
    # [claude, codex]. Anyone reaching for sessions[0] as the leader gets it
    # exactly backwards AND gets a plausible-looking answer, which is the
    # worst combination available. The classifier ignores position entirely.
    roles = classify_phase_sessions(phase_provider=phase_provider, sessions=sessions)

    leader: str | None = None
    unattributable: list[str] = []
    delegate_ids: list[str] = []
    for session_id, role in roles.items():
        if role is SessionRole.LEADER:
            leader = session_id
        elif role is SessionRole.DELEGATE:
            delegate_ids.append(session_id)
        else:
            unattributable.append(session_id)

    # Sequential rather than gathered: this runs against a store that is a
    # network boundary, and a phase's delegate count is small. Concurrency
    # here would buy little and would make the failure of one lookup harder
    # to keep isolated to its own session.
    # An explicit loop, not a comprehension: an ``await`` inside a generator
    # expression makes it an async generator, which ``tuple()`` cannot consume.
    delegates: list[DelegateCost] = []
    for session_id in delegate_ids:
        usage = await resolve_delegate_usage(store, session_id)
        delegates.append(DelegateCost(session_id=session_id, usage=usage))

    return PhaseReconciliation(
        leader_session_id=leader,
        delegates=tuple(delegates),
        unattributable=tuple(unattributable),
    )
