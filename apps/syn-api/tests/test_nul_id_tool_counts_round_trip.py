"""The executions list must count tools under the id the tally holds (#1241).

``_fetch_tool_counts`` binds execution ids into ``execution_id = ANY($1)`` and
then RETURNS A MAPPING KEYED BY THOSE IDS, so it has two ways to lose the
answer: ask for a spelling no row carries, or answer under a key no caller
looks up. Either shows the same thing on the dashboard - an execution with 0
tool calls, which is a perfectly ordinary number.

The double holds its rows under the spelling the writer produced and serves
them only to a query that asks for it, which is all Postgres does here. The
table behind it changed in #1322 - from ``agent_events`` to the tally - and
the round trip this pins is the reason that move had to preserve the spelling:
the tally is keyed by the same sanitised id the events were.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

#: One column value as asyncpg would hand it back - named rather than erased,
#: because the untyped-dicts ratchet counts test files too.
type _Cell = str | int

NUL = chr(0)
LONE_SURROGATE = chr(0xDEAD)

from syn_domain.storable_text import pg_safe  # noqa: E402

RAW_ID = "exec-" + NUL + "abc" + LONE_SURROGATE + "def"
#: Derived rather than written out: the derivation IS the policy, and stripping
#: alone is not injective, so a marker recording the alteration is appended.
STORED_ID = pg_safe(RAW_ID)


def _stored_spelling() -> str:
    """What the WRITER makes of ``RAW_ID`` - asked, not assumed."""
    from syn_adapters.events.models import AgentEvent

    event = AgentEvent(event_type="tool_execution_completed", execution_id=RAW_ID)
    assert event.execution_id is not None
    return event.execution_id


class _Tally:
    def __init__(self) -> None:
        self.binds: list[tuple[object, ...]] = []

    async def fetch(self, _query: str, *args: object) -> list[dict[str, _Cell]]:
        self.binds.append(args)
        wanted = args[0]
        assert isinstance(wanted, list)
        if STORED_ID not in wanted:
            return []
        return [{"execution_id": STORED_ID, "cnt": 7}]


class _Acquire:
    def __init__(self, conn: _Tally) -> None:
        self._conn = conn

    async def __aenter__(self) -> _Tally:
        return self._conn

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _Pool:
    def __init__(self, conn: _Tally) -> None:
        self.conn = conn

    def acquire(self) -> _Acquire:
        return _Acquire(self.conn)


class _EventStore:
    def __init__(self, pool: _Pool) -> None:
        self.pool = pool


async def test_tool_counts_round_trip_for_a_nul_bearing_execution_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from syn_api import _wiring
    from syn_api.routes.executions.queries import _fetch_tool_counts

    assert _stored_spelling() == STORED_ID
    store = _EventStore(_Pool(_Tally()))
    monkeypatch.setattr(_wiring, "get_event_store_instance", lambda: store)

    counts = await _fetch_tool_counts([RAW_ID])

    # Found at all - and filed under the key a caller holding a stored id
    # will look up, which is the second half of the same failure.
    assert counts == {STORED_ID: 7}
