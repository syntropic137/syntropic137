"""Turning one phase's capture into priced delegate usage (#895).

The composition step: classify the phase's stored sessions, then price only
the ones that are not already priced. Its whole job is to be the place where
"which sessions did this phase produce" becomes "what did the unbilled ones
cost", without ever pricing the leader a second time.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.agent_sessions.delegate_usage import StoredSession
from syn_domain.contexts.agent_sessions.phase_reconciliation import (
    reconcile_phase_delegates,
)
from syn_domain.contexts.agent_sessions.transcript_usage import (
    PricedUsage,
    UnpricedUsage,
)


class FakeStore:
    """A store stub that records what was asked of it.

    The recording matters more than the returning: the sharpest assertion in
    this module is that the leader is never even LOOKED UP, which a stub that
    only returns values cannot express.
    """

    def __init__(self, sessions: dict[str, StoredSession] | None = None) -> None:
        self._sessions = sessions or {}
        self.requested: list[str] = []

    async def fetch_session(self, session_id: str) -> StoredSession | None:
        self.requested.append(session_id)
        return self._sessions.get(session_id)

    def arrives(self, session: StoredSession) -> None:
        """Capture lands for a session that was not there a moment ago."""
        self._sessions[session.session_id] = session


def _claude_session(session_id: str, output_tokens: int) -> StoredSession:
    """A minimal well-formed claude transcript worth a known number of tokens."""
    line = {
        "type": "assistant",
        "message": {
            "model": "claude-opus-4",
            "usage": {
                "input_tokens": 10,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "output_tokens": output_tokens,
            },
        },
    }
    import json

    return StoredSession(
        session_id=session_id,
        source_format="claude-code-jsonl",
        raw=json.dumps(line),
    )


@pytest.mark.unit
class TestTheLeaderIsNeverPricedAgain:
    async def test_the_leader_is_not_even_looked_up(self) -> None:
        """The invariant this module exists to hold.

        The leader's tokens are already recorded as token_usage rows. Not
        fetching it at all is a stronger guarantee than fetching and
        discarding, because there is then no code path on which its number
        could reach a total.
        """
        store = FakeStore({"s-claude": _claude_session("s-claude", 500)})

        result = await reconcile_phase_delegates(
            store=store,
            phase_provider="codex",
            sessions=[("s-codex", "Codex"), ("s-claude", "ClaudeCode")],
        )

        assert store.requested == ["s-claude"]
        assert result.leader_session_id == "s-codex"
        assert [d.session_id for d in result.delegates] == ["s-claude"]

    async def test_a_phase_that_delegated_nothing_prices_nothing(self) -> None:
        store = FakeStore()

        result = await reconcile_phase_delegates(
            store=store, phase_provider="claude", sessions=[("s-claude", "ClaudeCode")]
        )

        assert store.requested == []
        assert result.delegates == ()
        assert result.unattributable == ()


@pytest.mark.unit
class TestDelegatesArePriced:
    async def test_a_delegate_carries_its_recovered_usage(self) -> None:
        store = FakeStore({"s-claude": _claude_session("s-claude", 500)})

        result = await reconcile_phase_delegates(
            store=store,
            phase_provider="codex",
            sessions=[("s-codex", "Codex"), ("s-claude", "ClaudeCode")],
        )

        usage = result.delegates[0].usage
        assert isinstance(usage, PricedUsage)
        assert usage.output_tokens == 500

    async def test_every_delegate_is_priced_not_just_the_first(self) -> None:
        store = FakeStore(
            {
                "s-a": _claude_session("s-a", 100),
                "s-b": _claude_session("s-b", 200),
            }
        )

        result = await reconcile_phase_delegates(
            store=store,
            phase_provider="codex",
            sessions=[("s-codex", "Codex"), ("s-a", "ClaudeCode"), ("s-b", "ClaudeCode")],
        )

        outputs = sorted(
            d.usage.output_tokens for d in result.delegates if isinstance(d.usage, PricedUsage)
        )
        assert outputs == [100, 200]


@pytest.mark.unit
class TestOneBadDelegateDoesNotSinkThePhase:
    async def test_a_missing_delegate_is_unpriced_and_its_sibling_still_prices(
        self,
    ) -> None:
        """An import runs over many sessions. One that is missing must cost
        that session its price, not cost the phase its run.
        """
        store = FakeStore({"s-b": _claude_session("s-b", 200)})

        result = await reconcile_phase_delegates(
            store=store,
            phase_provider="codex",
            sessions=[("s-codex", "Codex"), ("s-a", "ClaudeCode"), ("s-b", "ClaudeCode")],
        )

        by_id = {d.session_id: d.usage for d in result.delegates}
        assert isinstance(by_id["s-a"], UnpricedUsage)
        assert isinstance(by_id["s-b"], PricedUsage)

    async def test_a_delegate_is_reported_even_when_unpriceable(self) -> None:
        """Unpriced-and-visible, never dropped. A dropped session is
        indistinguishable from a phase that never delegated.
        """
        store = FakeStore()

        result = await reconcile_phase_delegates(
            store=store,
            phase_provider="codex",
            sessions=[("s-codex", "Codex"), ("s-a", "ClaudeCode")],
        )

        assert [d.session_id for d in result.delegates] == ["s-a"]
        assert isinstance(result.delegates[0].usage, UnpricedUsage)


@pytest.mark.unit
class TestUnattributablePhasesPriceNothing:
    async def test_same_harness_fanout_prices_nothing_and_is_reported(self) -> None:
        """The known limit, held explicitly rather than by omission.

        Neither session can be shown to be the delegate, so pricing either
        risks pricing the leader. Both are reported as unattributable so an
        operator can see there IS unpriced work here.
        """
        store = FakeStore({"s-a": _claude_session("s-a", 100), "s-b": _claude_session("s-b", 200)})

        result = await reconcile_phase_delegates(
            store=store,
            phase_provider="claude",
            sessions=[("s-a", "ClaudeCode"), ("s-b", "ClaudeCode")],
        )

        assert store.requested == []
        assert result.delegates == ()
        assert result.leader_session_id is None
        assert sorted(result.unattributable) == ["s-a", "s-b"]

    async def test_no_session_is_ever_silently_dropped(self) -> None:
        """Whatever the classification, every captured id must appear
        somewhere in the result. Losing one by omission is how unpriced work
        becomes invisible instead of merely unpriced.
        """
        sessions = [("s-codex", "Codex"), ("s-a", "ClaudeCode"), ("s-b", "ClaudeCode")]
        store = FakeStore()

        result = await reconcile_phase_delegates(
            store=store, phase_provider="codex", sessions=sessions
        )

        accounted = (
            {result.leader_session_id}
            | {d.session_id for d in result.delegates}
            | set(result.unattributable)
        )
        assert accounted == {sid for sid, _ in sessions}


@pytest.mark.unit
class TestOrderIsNotADiscriminator:
    """Position in the captured tuple means nothing, and the obvious guess is
    backwards.

    On real capture (exec-3e9d39a64539, a codex-led phase) the tuple is
    [claude, codex]: the DELEGATE comes first. Reaching for index 0 as the
    leader returns a wrong answer that looks entirely plausible, so this is
    pinned rather than left to a comment.
    """

    #: The real ids from exec-3e9d39a64539, in the order capture recorded them.
    REAL_CAPTURE = (
        ("c5e2715f-0a7a-4dde-a8bd-07369601cc94", "ClaudeCode"),
        ("01a0472d-0815-79b0-bda7-ea7c9cb51686", "Codex"),
    )

    async def test_the_delegate_may_come_first(self) -> None:
        result = await reconcile_phase_delegates(
            store=FakeStore(), phase_provider="codex", sessions=self.REAL_CAPTURE
        )

        assert result.leader_session_id == "01a0472d-0815-79b0-bda7-ea7c9cb51686"
        assert [d.session_id for d in result.delegates] == ["c5e2715f-0a7a-4dde-a8bd-07369601cc94"]

    async def test_reversing_the_tuple_changes_nothing(self) -> None:
        forward = await reconcile_phase_delegates(
            store=FakeStore(), phase_provider="codex", sessions=self.REAL_CAPTURE
        )
        reverse = await reconcile_phase_delegates(
            store=FakeStore(),
            phase_provider="codex",
            sessions=list(reversed(self.REAL_CAPTURE)),
        )

        assert forward.leader_session_id == reverse.leader_session_id
        assert {d.session_id for d in forward.delegates} == {
            d.session_id for d in reverse.delegates
        }


@pytest.mark.unit
class TestTooEarlyIsDistinguishableFromAbsent:
    """The capture race, which fails SILENTLY if these two look alike.

    Capture lands after the execution reports completed. A reader arriving
    promptly sees an empty store for sessions that appear seconds later, and a
    caller that treats that as "nothing to import" reports success having
    imported nothing.
    """

    async def test_a_delegate_the_store_lacks_is_flagged_absent(self) -> None:
        result = await reconcile_phase_delegates(
            store=FakeStore(),
            phase_provider="codex",
            sessions=[("s-codex", "Codex"), ("s-a", "ClaudeCode")],
        )

        assert result.absent_delegate_ids == ("s-a",)

    async def test_an_unreadable_delegate_is_not_flagged_absent(self) -> None:
        """The distinction that makes the flag worth having.

        This transcript IS present, so asking again will never help. Retrying
        it forever is a different bug from finalising too early, and the flag
        exists to keep them apart.
        """
        store = FakeStore(
            {
                "s-a": StoredSession(
                    session_id="s-a",
                    source_format="claude-code-jsonl",
                    raw="{not json at all",
                )
            }
        )

        result = await reconcile_phase_delegates(
            store=store,
            phase_provider="codex",
            sessions=[("s-codex", "Codex"), ("s-a", "ClaudeCode")],
        )

        assert isinstance(result.delegates[0].usage, UnpricedUsage)
        assert result.absent_delegate_ids == ()

    async def test_a_priced_delegate_is_not_flagged_absent(self) -> None:
        store = FakeStore({"s-a": _claude_session("s-a", 100)})

        result = await reconcile_phase_delegates(
            store=store,
            phase_provider="codex",
            sessions=[("s-codex", "Codex"), ("s-a", "ClaudeCode")],
        )

        assert result.absent_delegate_ids == ()

    async def test_the_early_read_is_not_mistaken_for_a_finished_one(self) -> None:
        """The race itself, played out against one store.

        First read: capture has not landed, so the delegate is absent and the
        caller must NOT finalise. Second read: it landed, and the same call
        prices it. Nothing about the phase changed in between.
        """
        store = FakeStore()
        sessions = [("s-codex", "Codex"), ("s-a", "ClaudeCode")]

        early = await reconcile_phase_delegates(
            store=store, phase_provider="codex", sessions=sessions
        )
        assert early.absent_delegate_ids == ("s-a",)

        store.arrives(_claude_session("s-a", 400))

        later = await reconcile_phase_delegates(
            store=store, phase_provider="codex", sessions=sessions
        )
        assert later.absent_delegate_ids == ()
        usage = later.delegates[0].usage
        assert isinstance(usage, PricedUsage)
        assert usage.output_tokens == 400
