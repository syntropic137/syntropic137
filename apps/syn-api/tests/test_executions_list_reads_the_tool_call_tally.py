"""``GET /executions`` reads tool calls from the tally, not from events (#1322).

The fifth copy of the slow count lived in the route itself, under a
``try/except Exception: return {}`` - so the 4-30s page never failed, it just
took 4-30s. Same table, same unindexable ``event_type`` filter, same fix.

The sibling proof for the four domain read paths is
``packages/syn-domain/tests/test_no_read_path_counts_tool_events.py``; this
one covers the route's own query, and that its fail-soft behaviour survived
the change - a dashboard that 500s because a tally row is missing is worse
than one showing a dash.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

import pytest

from syn_domain import tool_call_counts
from syn_shared.events import TOOL_EXECUTION_COMPLETED

pytestmark = pytest.mark.unit

_EXECUTION = "exec-1322"


@dataclass(frozen=True)
class _TallyRow:
    """One tally row, read by column name the way asyncpg's ``Record`` is.

    Named and typed fields rather than a str-keyed dict, because the shape is
    fixed: it is the two columns ``_BY_EXECUTION_IDS_SQL`` selects. Raising
    ``KeyError`` for anything else is what a ``Record`` does, so a read path
    that asks for a column this query never selected fails here rather than
    being handed a value Postgres would not have had.
    """

    execution_id: str
    cnt: int

    def __getitem__(self, column: str) -> object:
        if column not in {f.name for f in fields(self)}:
            raise KeyError(column)
        return getattr(self, column)


class _RecordingConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.args: list[tuple[object, ...]] = []

    async def fetch(self, query: str, *args: object) -> list[_TallyRow]:
        self.statements.append(query)
        self.args.append(args)
        if tool_call_counts.TABLE not in query:
            return []
        return [_TallyRow(execution_id=_EXECUTION, cnt=11)]


class _Acquire:
    def __init__(self, conn: _RecordingConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> _RecordingConnection:
        return self._conn

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _Pool:
    def __init__(self, conn: _RecordingConnection) -> None:
        self._conn = conn

    def acquire(self) -> _Acquire:
        return _Acquire(self._conn)


class _EventStore:
    def __init__(self, pool: _Pool | None) -> None:
        self.pool = pool


def _install(monkeypatch: pytest.MonkeyPatch, store: _EventStore) -> None:
    from syn_api import _wiring

    monkeypatch.setattr(_wiring, "get_event_store_instance", lambda: store)


async def test_the_route_counts_tools_from_the_tally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from syn_api.routes.executions.queries import _fetch_tool_counts

    conn = _RecordingConnection()
    _install(monkeypatch, _EventStore(_Pool(conn)))

    counts = await _fetch_tool_counts([_EXECUTION])

    assert counts == {_EXECUTION: 11}
    assert conn.statements, "the route asked the database nothing"
    for statement, args in zip(conn.statements, conn.args, strict=True):
        assert "agent_events" not in statement, f"still reading agent_events: {statement}"
        assert TOOL_EXECUTION_COMPLETED not in statement
        assert TOOL_EXECUTION_COMPLETED not in {str(arg) for arg in args}


async def test_a_missing_tally_leaves_the_page_renderable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No pool, no counts, no exception - the list is more than one column."""
    _install(monkeypatch, _EventStore(None))

    from syn_api.routes.executions.queries import _fetch_tool_counts

    assert await _fetch_tool_counts([_EXECUTION]) == {}
