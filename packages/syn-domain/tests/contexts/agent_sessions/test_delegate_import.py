"""The import writes delegates and never the leader (#895)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.transcript_usage import PricedUsage

from syn_domain.contexts.agent_sessions.delegate_import import import_phase_delegates
from syn_domain.contexts.agent_sessions.delegate_usage import StoredSession
from syn_domain.contexts.agent_sessions.import_identity import platform_session_id_for

pytestmark = pytest.mark.unit


def _claude_session(session_id: str, output_tokens: int) -> StoredSession:
    line = {
        "message": {
            "model": "claude-sonnet-5",
            "usage": {
                "input_tokens": 10,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "output_tokens": output_tokens,
            },
        }
    }
    return StoredSession(
        session_id=session_id, source_format="claude-code-jsonl", raw=json.dumps(line)
    )


@dataclass
class _Store:
    sessions: dict[str, StoredSession]
    fetched: list[str] = field(default_factory=list)

    async def fetch_session(self, session_id: str) -> StoredSession | None:
        self.fetched.append(session_id)
        return self.sessions.get(session_id)


@dataclass
class _Writer:
    written: list[tuple[str, PricedUsage | None, str | None]] = field(default_factory=list)

    async def record_delegate_usage(
        self,
        *,
        session_id: str,
        usage: PricedUsage | None,
        unpriced_reason: str | None,
        execution_id: str,
        phase_id: str,
        workspace_id: str | None,
    ) -> None:
        self.written.append((session_id, usage, unpriced_reason))


async def _run(
    store: _Store, writer: _Writer, *, leader: str | None, captured: list[str], attempts: int = 3
):
    return await import_phase_delegates(
        store,
        writer,
        leader_native_session_id=leader,
        captured_session_ids=captured,
        execution_id="exec-1",
        phase_id="phase-1",
        attempts_remaining=attempts,
    )


class TestTheLeaderIsNeverWritten:
    async def test_the_leader_is_not_written_and_not_even_fetched(self) -> None:
        """The overcount guard. An undercount surfaces as a missing delegate;
        an overcount just looks like expensive work, so nobody reports it."""
        store = _Store(
            {"s-lead": _claude_session("s-lead", 100), "s-del": _claude_session("s-del", 7)}
        )
        writer = _Writer()

        result = await _run(store, writer, leader="s-lead", captured=["s-lead", "s-del"])

        assert [sid for sid, _, _ in writer.written] == [platform_session_id_for("s-del")]
        assert "s-lead" not in store.fetched
        assert [d.harness_session_id for d in result.imported] == ["s-del"]

    async def test_a_solo_phase_writes_nothing(self) -> None:
        store = _Store({"s-lead": _claude_session("s-lead", 100)})
        writer = _Writer()

        result = await _run(store, writer, leader="s-lead", captured=["s-lead"])

        assert writer.written == []
        assert result.imported == ()
        assert result.may_finalise


class TestTheHoleTheOldDesignHad:
    async def test_claude_delegating_to_claude_is_priced(self) -> None:
        """Two sessions, same harness. The classify-by-agent-name design called
        both unattributable and priced neither; this is the case that made the
        rewrite worth doing."""
        store = _Store({"s-a": _claude_session("s-a", 100), "s-b": _claude_session("s-b", 42)})
        writer = _Writer()

        result = await _run(store, writer, leader="s-a", captured=["s-a", "s-b"])

        assert len(writer.written) == 1
        session_id, usage, _ = writer.written[0]
        assert session_id == platform_session_id_for("s-b")
        assert usage is not None
        assert usage.output_tokens == 42
        assert result.imported[0].priced


class TestABrokenIdentityAssumptionRefuses:
    async def test_a_leader_absent_from_the_sweep_writes_nothing(self) -> None:
        """Neither importing all (bills the leader twice) nor importing none
        (drops real delegates) is safe, so it refuses and says so."""
        store = _Store({"s-x": _claude_session("s-x", 5)})
        writer = _Writer()

        result = await _run(store, writer, leader="s-unknown", captured=["s-x"])

        assert writer.written == []
        assert result.leader_missing_from_sweep
        assert not result.may_finalise

    async def test_no_announced_leader_writes_nothing(self) -> None:
        store = _Store({"s-x": _claude_session("s-x", 5)})
        writer = _Writer()

        result = await _run(store, writer, leader=None, captured=["s-x"])

        assert writer.written == []
        assert result.leader_missing_from_sweep

    async def test_an_empty_sweep_is_not_an_error(self) -> None:
        result = await _run(_Store({}), _Writer(), leader="s-lead", captured=[])
        assert not result.leader_missing_from_sweep
        assert result.may_finalise


class TestAnUnpriceableDelegateStaysVisible:
    async def test_a_delegate_the_store_does_not_have_is_held_for_retry(self) -> None:
        store = _Store({"s-lead": _claude_session("s-lead", 1)})
        writer = _Writer()

        result = await _run(
            store, writer, leader="s-lead", captured=["s-lead", "s-gone"], attempts=2
        )

        assert writer.written == []
        assert result.retry_ids == ("s-gone",)
        assert not result.may_finalise

    async def test_with_no_budget_left_it_is_written_as_a_named_gap(self) -> None:
        """Finalising with a VISIBLE gap beats retrying forever, and beats a
        silent drop that reads as 'this delegate never ran'."""
        store = _Store({"s-lead": _claude_session("s-lead", 1)})
        writer = _Writer()

        result = await _run(
            store, writer, leader="s-lead", captured=["s-lead", "s-gone"], attempts=0
        )

        assert len(writer.written) == 1
        _, usage, reason = writer.written[0]
        assert usage is None
        assert reason
        assert result.exhausted
        assert result.may_finalise
        assert not result.imported[0].priced


class TestReimportIsIdempotentByConstruction:
    async def test_the_same_delegate_derives_the_same_platform_id(self) -> None:
        store = _Store(
            {"s-lead": _claude_session("s-lead", 1), "s-del": _claude_session("s-del", 9)}
        )
        first = _Writer()
        second = _Writer()

        await _run(store, first, leader="s-lead", captured=["s-lead", "s-del"])
        await _run(store, second, leader="s-lead", captured=["s-lead", "s-del"])

        assert [s for s, _, _ in first.written] == [s for s, _, _ in second.written]
