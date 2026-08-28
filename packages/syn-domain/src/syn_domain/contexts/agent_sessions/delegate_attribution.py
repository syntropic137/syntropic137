"""Deciding which of a phase's stored sessions are DELEGATES (issue #895).

THE ASYMMETRY THAT DRIVES EVERY CHOICE HERE: the leader's tokens are already
recorded as token_usage rows under its platform session. Importing the leader
a second time INFLATES the execution total, and an inflated cost is worse than
a missing one because it looks like data. It also inflates precisely the
fan-out someone runs in order to control spend. So an undercount is
recoverable and an overcount is not, and everything below refuses rather than
guesses.

WHY LEADERSHIP MUST BE INFERRED AT ALL: the platform mints a uuid4 session id
per phase run, the harness picks its own, and nothing maps one to the other.
The phase's capture reports the harness ids it saw, as a flat tuple with no
edge, so which one led is not recorded anywhere.

WHAT THIS CAN AND CANNOT DO. Cross-harness delegation is separable: the
leader's agent matches the phase's declared provider and a delegate's does
not. Same-harness fan-out is NOT: identical agent, identical tags, no edge,
either could be the leader. That case returns UNATTRIBUTABLE and stays
unpriced until the delegation edge events carry the parentage explicitly.
That is a known limit, not an oversight.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

#: How a store reports each harness, mapped to the provider a phase declares.
#: Both sides are external vocabularies, so this is the one place they meet.
_AGENT_BY_PROVIDER: dict[str, str] = {
    "claude": "ClaudeCode",
    "codex": "Codex",
}


class SessionRole(StrEnum):
    """What one stored session was to its phase."""

    LEADER = "leader"
    """The phase's own agent. Already priced; must never be imported again."""

    DELEGATE = "delegate"
    """Work the leader handed off. Priced nowhere today; the thing to import."""

    UNATTRIBUTABLE = "unattributable"
    """Present, but which one it was cannot be established.

    Deliberately not a third guess. Unpriced-and-visible beats priced-wrongly,
    because an operator can chase a gap and cannot chase a number that is
    quietly too big.
    """


def classify_phase_sessions(
    phase_provider: str, sessions: Sequence[tuple[str, str]]
) -> dict[str, SessionRole]:
    """Assign a role to each ``(session_id, agent)`` a phase produced.

    Args:
        phase_provider: The provider the phase DECLARED, which is the one the
            platform already created a session for and already priced.
        sessions: The harness sessions the store confirmed for this phase.

    Returns:
        A role per session id. Every id is present, so a caller cannot lose
        one by omission: an unattributable session is reported as such rather
        than dropped.
    """
    if not sessions:
        return {}

    def refuse_all() -> dict[str, SessionRole]:
        return {session_id: SessionRole.UNATTRIBUTABLE for session_id, _ in sessions}

    leader_agent = _AGENT_BY_PROVIDER.get(phase_provider)
    if leader_agent is None:
        # An unknown provider means the discriminator does not apply, so every
        # id is a guess.
        return refuse_all()

    # A capture tuple is not guaranteed to hold distinct ids, and the two ways
    # it can repeat one pull in opposite directions. The same id listed twice
    # with the SAME agent is one session named twice, and must not be counted
    # as a rival candidate. The same id with DIFFERENT agents is contradictory:
    # a session cannot have been two harnesses, so something upstream is wrong
    # and the phase is refused rather than resolved by whichever row came last.
    agent_by_session: dict[str, str] = {}
    for session_id, agent in sessions:
        seen = agent_by_session.setdefault(session_id, agent)
        if seen != agent:
            # Its neighbours go too: if the capture contradicts itself about
            # one session, its account of the others is not trustworthy
            # either, and pricing a delegate on that basis risks pricing the
            # leader.
            return refuse_all()

    candidates = [
        session_id for session_id, agent in agent_by_session.items() if agent == leader_agent
    ]

    # Exactly one candidate leader, or none of this is safe. Zero means the
    # assumption that the leader is present has failed. More than one means we
    # cannot tell which was the phase's own agent, and importing the wrong one
    # double-counts the session already priced.
    if len(candidates) != 1:
        return refuse_all()

    leader = candidates[0]
    return {
        session_id: SessionRole.LEADER if session_id == leader else SessionRole.DELEGATE
        for session_id, _ in sessions
    }
