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

import json
import pathlib

import pytest

from syn_domain.contexts.agent_sessions.delegate_attribution import (
    _AGENT_BY_PROVIDER,
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


@pytest.mark.unit
class TestTheVocabulariesItBridgesStayPinned:
    """This module is the one place two EXTERNAL vocabularies meet, so drift
    in either one is silent: the classifier simply stops recognising a leader
    and every phase becomes unattributable. That fails safe (an undercount,
    never a double count) but it fails QUIETLY, which is how a whole harness
    could stop being priced without a single test going red. These pin both
    sides to the real sources.
    """

    def test_provider_keys_match_the_workflow_definition_literal(self) -> None:
        """The declared-provider side, pinned to its source of truth.

        ``AgentYamlDefinition.provider`` is a ``Literal`` in the orchestration
        context. Importing it here would couple two bounded contexts, so the
        value is copied and this test guards the copy. A new provider added
        there turns this red instead of silently going unpriced.
        """
        from typing import get_args

        from syn_domain.contexts.orchestration._shared.workflow_definition import (
            AgentYamlDefinition,
        )

        def string_literals(annotation: object) -> set[str]:
            """Collect the string members of a possibly-nested annotation.

            The field is ``Literal["claude", "codex"] | None``, so one
            ``get_args`` yields the union members rather than the strings.
            """
            args = get_args(annotation)
            if not args:
                return set()
            found: set[str] = set()
            for arg in args:
                if isinstance(arg, str):
                    found.add(arg)
                else:
                    found |= string_literals(arg)
            return found

        providers = string_literals(AgentYamlDefinition.model_fields["provider"].annotation)

        assert providers, "the provider Literal was not found; this test has rotted"
        assert providers == set(_AGENT_BY_PROVIDER)

    def test_agent_names_match_the_recorded_store_values(self) -> None:
        """The store side, pinned to real redacted records rather than to my
        memory of what the store emits.
        """
        records = json.loads(
            (
                pathlib.Path(__file__).parents[2] / "fixtures/delegation/store_session_records.json"
            ).read_text()
        )
        recorded = {record["agent"] for record in records.values()}

        assert recorded == set(_AGENT_BY_PROVIDER.values())


@pytest.mark.unit
def test_a_foreign_provider_vocabulary_fails_safe() -> None:
    """A caller reaching for the WRONG provider field must not double count.

    The workspace image manifest spells the same provider ``claude-cli``, a
    third vocabulary. Passing that instead of the phase's declared provider
    must yield no leader and no delegate, so the mistake costs an undercount
    rather than importing a session that is already priced.
    """
    roles = classify_phase_sessions(
        phase_provider="claude-cli",
        sessions=[_session("s-claude", "ClaudeCode"), _session("s-codex", "Codex")],
    )

    assert set(roles.values()) == {SessionRole.UNATTRIBUTABLE}


@pytest.mark.unit
class TestRepeatedIdsInTheCapture:
    """A capture tuple is not guaranteed to hold distinct ids, and the two
    ways it can repeat one pull in opposite directions.
    """

    def test_the_same_session_listed_twice_is_still_one_leader(self) -> None:
        """A repeat must not be mistaken for a rival candidate.

        One session named twice is still one session. Counting the repeat as a
        second candidate leader refuses a phase that is perfectly
        determinable, which costs a real delegate its price for no reason.
        """
        roles = classify_phase_sessions(
            phase_provider="codex",
            sessions=[
                _session("s-codex", "Codex"),
                _session("s-codex", "Codex"),
                _session("s-claude", "ClaudeCode"),
            ],
        )

        assert roles["s-codex"] is SessionRole.LEADER
        assert roles["s-claude"] is SessionRole.DELEGATE

    def test_a_repeated_delegate_is_priced_once(self) -> None:
        """The result is keyed by session id, so a repeat cannot become two
        delegates and be charged twice.
        """
        roles = classify_phase_sessions(
            phase_provider="codex",
            sessions=[
                _session("s-codex", "Codex"),
                _session("s-claude", "ClaudeCode"),
                _session("s-claude", "ClaudeCode"),
            ],
        )

        assert roles == {
            "s-codex": SessionRole.LEADER,
            "s-claude": SessionRole.DELEGATE,
        }

    def test_one_id_with_two_different_agents_refuses(self) -> None:
        """Contradictory data must not resolve to a confident answer.

        The same session cannot have been two different harnesses. Something
        upstream is wrong, and the one thing that must not happen is quietly
        picking whichever row came last and treating the result as known.
        """
        roles = classify_phase_sessions(
            phase_provider="codex",
            sessions=[_session("s-a", "Codex"), _session("s-a", "ClaudeCode")],
        )

        assert roles == {"s-a": SessionRole.UNATTRIBUTABLE}

    def test_one_contradictory_id_refuses_the_whole_phase(self) -> None:
        """Its neighbours are refused too. If the capture is contradictory
        about one session, its account of the others is not trustworthy
        either, and pricing a delegate on that basis risks pricing the leader.
        """
        roles = classify_phase_sessions(
            phase_provider="codex",
            sessions=[
                _session("s-a", "Codex"),
                _session("s-a", "ClaudeCode"),
                _session("s-b", "ClaudeCode"),
            ],
        )

        assert set(roles.values()) == {SessionRole.UNATTRIBUTABLE}
        assert set(roles) == {"s-a", "s-b"}


@pytest.mark.unit
def test_agent_matching_is_exact_and_fails_safe() -> None:
    """A differently-cased agent name is not a match.

    Loosening this would be the wrong instinct: a fuzzy match that guesses
    right most of the time is how the leader eventually gets priced. Exact
    matching means an unrecognised spelling costs an undercount, which is the
    direction this whole module errs in.
    """
    roles = classify_phase_sessions(
        phase_provider="codex",
        sessions=[_session("s-x", "codex"), _session("s-a", "ClaudeCode")],
    )

    assert set(roles.values()) == {SessionRole.UNATTRIBUTABLE}
