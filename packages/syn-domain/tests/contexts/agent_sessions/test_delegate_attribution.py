"""Deciding which stored sessions a phase produced are DELEGATES (#895).

This is where the double-count risk lives, and double-counting is worse than
the undercount we have today. The leader's tokens are ALREADY recorded as
token_usage rows under its platform session, so importing the leader a second
time inflates the execution total. An inflated cost is worse than a missing
one because it looks like data, and it inflates exactly the fan-out someone
runs to control spend.

The platform mints its own session id and the harness picks its own; the two
are disjoint namespaces with no mapping. So leadership has to be INFERRED, and
this module refuses rather than guesses when it cannot be.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.agent_sessions.delegate_attribution import (
    SessionRole,
    classify_phase_sessions,
)


def _session(session_id: str, agent: str) -> tuple[str, str]:
    return (session_id, agent)


@pytest.mark.unit
class TestCrossHarnessDelegationIsSeparable:
    """The case that works today: the leader's agent matches the phase's
    declared provider and the delegate's does not.
    """

    def test_the_agent_matching_the_phase_provider_is_the_leader(self) -> None:
        roles = classify_phase_sessions(
            phase_provider="codex",
            sessions=[_session("s-codex", "Codex"), _session("s-claude", "ClaudeCode")],
        )

        assert roles["s-codex"] is SessionRole.LEADER
        assert roles["s-claude"] is SessionRole.DELEGATE

    def test_the_reverse_direction_too(self) -> None:
        roles = classify_phase_sessions(
            phase_provider="claude",
            sessions=[_session("s-claude", "ClaudeCode"), _session("s-codex", "Codex")],
        )

        assert roles["s-claude"] is SessionRole.LEADER
        assert roles["s-codex"] is SessionRole.DELEGATE

    def test_a_lone_leader_has_no_delegates(self) -> None:
        """A phase that delegated nothing must import nothing."""
        roles = classify_phase_sessions(
            phase_provider="claude", sessions=[_session("s-claude", "ClaudeCode")]
        )

        assert roles == {"s-claude": SessionRole.LEADER}

    def test_several_delegates_of_one_other_harness(self) -> None:
        roles = classify_phase_sessions(
            phase_provider="claude",
            sessions=[
                _session("s-claude", "ClaudeCode"),
                _session("s-codex-1", "Codex"),
                _session("s-codex-2", "Codex"),
            ],
        )

        assert roles["s-codex-1"] is SessionRole.DELEGATE
        assert roles["s-codex-2"] is SessionRole.DELEGATE


@pytest.mark.unit
class TestItRefusesRatherThanGuesses:
    def test_same_harness_fanout_is_unattributable(self) -> None:
        """The owner's stated direction, and the case this cannot serve.

        Two sessions of the SAME agent as the phase provider: identical tags,
        identical agent, no edge. Either could be the leader. Guessing risks
        importing the leader and inflating the total, so both are refused
        until the delegation edge exists.
        """
        roles = classify_phase_sessions(
            phase_provider="claude",
            sessions=[_session("s-a", "ClaudeCode"), _session("s-b", "ClaudeCode")],
        )

        assert set(roles.values()) == {SessionRole.UNATTRIBUTABLE}

    def test_no_session_matching_the_provider_is_unattributable(self) -> None:
        """If nothing matches the declared provider, the assumption that the
        leader is present has failed, and every id becomes a guess.
        """
        roles = classify_phase_sessions(
            phase_provider="codex", sessions=[_session("s-claude", "ClaudeCode")]
        )

        assert roles["s-claude"] is SessionRole.UNATTRIBUTABLE

    def test_an_unknown_provider_is_unattributable(self) -> None:
        roles = classify_phase_sessions(
            phase_provider="some-future-harness",
            sessions=[_session("s-a", "ClaudeCode"), _session("s-b", "Codex")],
        )

        assert set(roles.values()) == {SessionRole.UNATTRIBUTABLE}

    def test_an_empty_phase_yields_nothing(self) -> None:
        assert classify_phase_sessions(phase_provider="claude", sessions=[]) == {}


@pytest.mark.unit
class TestTheLeaderIsNeverImported:
    """The invariant that matters most: whatever else happens, the session
    already counted must not be counted again.
    """

    def test_exactly_one_leader_when_attributable(self) -> None:
        roles = classify_phase_sessions(
            phase_provider="codex",
            sessions=[
                _session("s-codex", "Codex"),
                _session("s-claude-1", "ClaudeCode"),
                _session("s-claude-2", "ClaudeCode"),
            ],
        )

        leaders = [sid for sid, role in roles.items() if role is SessionRole.LEADER]
        assert leaders == ["s-codex"]

    def test_two_sessions_matching_the_provider_refuses_all(self) -> None:
        """Two candidate leaders means we cannot tell which is which, so
        importing either risks importing the one already counted.
        """
        roles = classify_phase_sessions(
            phase_provider="codex",
            sessions=[
                _session("s-codex-1", "Codex"),
                _session("s-codex-2", "Codex"),
                _session("s-claude", "ClaudeCode"),
            ],
        )

        assert SessionRole.LEADER not in roles.values()
        assert SessionRole.DELEGATE not in roles.values()
