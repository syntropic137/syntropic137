"""The executions list must count tools under the id the tally holds (#1241).

The list's enrichment (``_load_execution_enrichment``, through the cost read's
``list_for_ids``) binds execution ids into ``execution_id = ANY($1)`` and
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

from dataclasses import dataclass, fields

import pytest

pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class _TallyRow:
    """One tally row, read by column name the way asyncpg's ``Record`` is.

    Named and typed fields rather than a str-keyed dict: the shape is the two
    columns the tally read selects, and a row whose ``execution_id`` is a
    declared ``str`` is one this file's whole point - the spelling that
    survives the round trip - can be stated about.
    """

    execution_id: str
    cnt: int

    def __getitem__(self, column: str) -> object:
        if column not in {f.name for f in fields(self)}:
            raise KeyError(column)
        return getattr(self, column)


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
    """Holds one execution's tally row and nothing else: no cost, no tokens."""

    def __init__(self) -> None:
        self.binds: list[tuple[object, ...]] = []

    def transaction(self, *, isolation: str, readonly: bool) -> _Transaction:
        return _Transaction()

    async def execute(self, _query: str, *_args: object) -> str:
        return "SET"

    async def fetch(self, query: str, *args: object) -> list[_TallyRow]:
        if "agent_tool_call_counts" not in query:
            return []
        self.binds.append(args)
        wanted = args[0]
        assert isinstance(wanted, list)
        if STORED_ID not in wanted:
            return []
        return [_TallyRow(execution_id=STORED_ID, cnt=7)]


class _Transaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc: object) -> bool:
        return False


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


class _Manager:
    def __init__(self, pool: _Pool) -> None:
        from syn_domain.contexts.orchestration.slices.execution_cost.projection import (
            ExecutionCostProjection,
        )

        self.execution_cost = ExecutionCostProjection(store=None, pool=pool)  # type: ignore[arg-type]  # a recording double


async def test_tool_counts_round_trip_for_a_nul_bearing_execution_id() -> None:
    from syn_api.routes.executions.queries import _load_execution_enrichment

    assert _stored_spelling() == STORED_ID
    tally = _Tally()

    enrichment = await _load_execution_enrichment(_Manager(_Pool(tally)), [RAW_ID])  # type: ignore[arg-type]  # a recording double

    # Found at all - and filed under the key a caller holding a stored id
    # will look up, which is the second half of the same failure.
    assert {eid: e.tool_call_count for eid, e in enrichment.items()} == {STORED_ID: 7}
    assert tally.binds == [([STORED_ID],)]
