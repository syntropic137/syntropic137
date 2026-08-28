"""A delegate must be billed ONCE per execution, however often import runs.

#933 (re-import doubles) and #936 (a session billed in one phase, recounted in
the next) are the same defect seen twice: the platform session id is
uuid5(namespace, harness_session_id) with no execution or phase in it, so the
same harness session captured twice writes two cost-bearing summaries under ONE
platform id, and the cost queries SUM them.

These tests are written to FAIL against HEAD. They assert what was BILLED, not
how many calls were made: a recording fake shows one call per import and stays
green while the real append-only store holds two rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from syn_domain.contexts.agent_sessions import import_phase_delegates
from syn_domain.contexts.agent_sessions.delegate_usage import StoredSession
from syn_domain.contexts.agent_sessions.import_ledger import InMemoryImportLedger

pytestmark = pytest.mark.unit

LEADER = "leader-1"
DELEGATE = "delegate-1"


def _claude(session_id: str, output: int, message_id: str) -> StoredSession:
    import json

    line = json.dumps(
        {
            "message": {
                "id": message_id,
                "model": "claude-sonnet-5",
                "usage": {
                    "input_tokens": 10,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "output_tokens": output,
                },
            }
        }
    )
    return StoredSession(session_id=session_id, source_format="claude-code-jsonl", raw=line)


@dataclass
class _Store:
    sessions: dict[str, StoredSession]

    async def fetch_session(self, session_id: str) -> StoredSession | None:
        return self.sessions.get(session_id)


@dataclass
class _AppendOnlyStore:
    """Stands in for agent_events: append-only, and the cost read SUMS.

    This is the whole point. A fake that records calls cannot express the
    defect, because the defect is that two rows both count.
    """

    rows: list[tuple[str, str, Decimal]] = field(default_factory=list)

    async def record_delegate_usage(
        self,
        *,
        session_id: str,
        usage: object,
        unpriced_reason: str | None,
        execution_id: str,
        phase_id: str,
        workspace_id: str | None,
    ) -> None:
        out = Decimal(str(getattr(usage, "output_tokens", 0) or 0))
        self.rows.append((session_id, execution_id, out))

    def billed_output_for(self, execution_id: str) -> Decimal:
        """What the cost query would report: the SUM over rows."""
        return sum((o for _, e, o in self.rows if e == execution_id), Decimal("0"))

    def cost_bearing_rows(self, execution_id: str) -> int:
        return sum(1 for _, e, o in self.rows if e == execution_id and o > 0)


async def _import(
    store: _Store,
    recorder: _AppendOnlyStore,
    *,
    phase: str,
    ledger: InMemoryImportLedger,
) -> None:
    await import_phase_delegates(
        store,
        recorder,
        leader_native_session_id=LEADER,
        captured_session_ids=[LEADER, DELEGATE],
        execution_id="exec-1",
        phase_id=phase,
        attempts_remaining=0,
        ledger=ledger,
    )


class TestTheSameDelegateIsBilledOncePerExecution:
    async def test_reimporting_one_phase_does_not_double_the_bill(self) -> None:
        """#933. A crash between the write and phase completion re-runs import."""
        store = _Store(
            {LEADER: _claude(LEADER, 100, "m-l"), DELEGATE: _claude(DELEGATE, 25, "m-d")}
        )
        recorder, ledger = _AppendOnlyStore(), InMemoryImportLedger()

        await _import(store, recorder, phase="phase-1", ledger=ledger)
        await _import(store, recorder, phase="phase-1", ledger=ledger)

        assert recorder.cost_bearing_rows("exec-1") == 1, (
            "a second import wrote a second cost-bearing row under the same "
            "session id; the cost query sums them"
        )
        assert recorder.billed_output_for("exec-1") == Decimal("25")

    async def test_a_session_billed_in_phase_one_is_not_rebilled_in_phase_two(self) -> None:
        """#936. The transcript is UNCHANGED, so the second phase owes nothing."""
        store = _Store(
            {LEADER: _claude(LEADER, 100, "m-l"), DELEGATE: _claude(DELEGATE, 25, "m-d")}
        )
        recorder, ledger = _AppendOnlyStore(), InMemoryImportLedger()

        await _import(store, recorder, phase="phase-1", ledger=ledger)
        await _import(store, recorder, phase="phase-2", ledger=ledger)

        assert recorder.billed_output_for("exec-1") == Decimal("25"), (
            "the same delegate was captured by two phases and billed twice"
        )

    async def test_a_grown_transcript_bills_only_the_delta(self) -> None:
        """The delegate really did more work; charge for that, not for all of it again."""
        store = _Store(
            {LEADER: _claude(LEADER, 100, "m-l"), DELEGATE: _claude(DELEGATE, 25, "m-d")}
        )
        recorder, ledger = _AppendOnlyStore(), InMemoryImportLedger()

        await _import(store, recorder, phase="phase-1", ledger=ledger)
        store.sessions[DELEGATE] = _claude(DELEGATE, 40, "m-d")
        await _import(store, recorder, phase="phase-2", ledger=ledger)

        assert recorder.billed_output_for("exec-1") == Decimal("40"), (
            "a grown cumulative transcript must total 40, not 25 + 40"
        )

    async def test_a_shrinking_transcript_is_refused_not_refunded(self) -> None:
        """A transcript cannot un-spend tokens.

        Smaller than what was billed means the store returned a different or
        truncated document. Charging a negative to reconcile would invent a
        refund, so the delta clamps at zero and the session is recorded as
        unpriced with the reason.
        """
        store = _Store(
            {LEADER: _claude(LEADER, 100, "m-l"), DELEGATE: _claude(DELEGATE, 40, "m-d")}
        )
        recorder, ledger = _AppendOnlyStore(), InMemoryImportLedger()

        await _import(store, recorder, phase="phase-1", ledger=ledger)
        store.sessions[DELEGATE] = _claude(DELEGATE, 25, "m-d")
        await _import(store, recorder, phase="phase-2", ledger=ledger)

        assert recorder.billed_output_for("exec-1") == Decimal("40"), (
            "a shrunken transcript must neither add nor subtract"
        )

    async def test_without_a_ledger_the_old_behaviour_is_unchanged(self) -> None:
        """The parameter is optional, so a caller that has not been wired yet
        keeps working - it simply keeps the double-count this fixes."""
        store = _Store(
            {LEADER: _claude(LEADER, 100, "m-l"), DELEGATE: _claude(DELEGATE, 25, "m-d")}
        )
        recorder = _AppendOnlyStore()

        await import_phase_delegates(
            store,
            recorder,
            leader_native_session_id=LEADER,
            captured_session_ids=[LEADER, DELEGATE],
            execution_id="exec-1",
            phase_id="phase-1",
            attempts_remaining=0,
        )

        assert recorder.cost_bearing_rows("exec-1") == 1
