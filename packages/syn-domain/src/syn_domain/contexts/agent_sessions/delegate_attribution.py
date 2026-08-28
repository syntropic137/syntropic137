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

from syn_shared.agents import AgentProvider

if TYPE_CHECKING:
    from collections.abc import Sequence

#: How a store reports each harness, mapped to the provider a phase declares.
#: Both sides are external vocabularies, so this is the one place they meet.
#:
#: Keyed by ``AgentProvider`` rather than by bare literals, so adding an
#: executable provider there without teaching this module its agent name is an
#: omission a reader can see rather than a silent one. The values are the
#: store's spelling, which no enum in this repo owns.
_AGENT_BY_PROVIDER: dict[str, str] = {
    AgentProvider.CLAUDE.value: "ClaudeCode",
    AgentProvider.CODEX.value: "Codex",
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


def _is_malformed(sessions: Sequence[tuple[str, str]]) -> bool:
    """A blank id or agent means the capture cannot be reasoned about.

    A blank id reaches a store lookup as an empty key, and its presence says
    the capture is malformed, so its account of the phase's other sessions is
    not worth trusting either.
    """
    return any(not session_id.strip() or not agent.strip() for session_id, agent in sessions)


def _agent_by_session(sessions: Sequence[tuple[str, str]]) -> dict[str, str] | None:
    """One agent per distinct session id, or None if the capture contradicts itself.

    A capture tuple is not guaranteed to hold distinct ids, and the two ways
    it can repeat one pull in opposite directions. The same id listed twice
    with the SAME agent is one session named twice, and collapsing it here
    stops it being counted as a rival candidate leader. The same id with
    DIFFERENT agents is contradictory - a session cannot have been two
    harnesses - so the capture is rejected outright rather than resolved by
    whichever row happened to come last.
    """
    collapsed: dict[str, str] = {}
    for session_id, agent in sessions:
        if collapsed.setdefault(session_id, agent) != agent:
            return None
    return collapsed


def _sole_leader(agent_by_session: dict[str, str], leader_agent: str) -> str | None:
    """The one session recorded as the phase's own agent, or None.

    None covers three refusals that all mean the same thing downstream: no
    candidate (the assumption that the leader is present has failed), several
    candidates (we cannot tell which was the phase's own agent), or an
    ambiguity that only casing conceals.

    That last one is the subtle case, and exact matching alone is NOT the
    conservative choice. For a phase declaring codex with sessions
    [("real-leader", "codex"), ("child", "Codex")], only the child matches
    exactly, so it would become the leader and the REAL leader would be
    classified a delegate - then fetched and priced. So a near-match is
    treated as ambiguity rather than as a non-match: if relaxing case would
    change which sessions are candidates, there is no sole leader.
    """
    candidates = {
        session_id for session_id, agent in agent_by_session.items() if agent == leader_agent
    }
    relaxed = {
        session_id
        for session_id, agent in agent_by_session.items()
        if agent.casefold() == leader_agent.casefold()
    }
    if relaxed != candidates or len(candidates) != 1:
        return None
    return next(iter(candidates))


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
    if leader_agent is None or _is_malformed(sessions):
        return refuse_all()

    agent_by_session = _agent_by_session(sessions)
    if agent_by_session is None:
        return refuse_all()

    leader = _sole_leader(agent_by_session, leader_agent)
    if leader is None:
        return refuse_all()

    return {
        session_id: SessionRole.LEADER if session_id == leader else SessionRole.DELEGATE
        for session_id, _ in sessions
    }
