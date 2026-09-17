"""The tool-call tally is written with the events it counts (#1322).

The read path no longer derives tool counts from ``agent_events``, so the
number is only as good as the write that maintains it. Two things have to
hold, and neither is visible from the read side:

1. The tally is written **inside the transaction that writes the events**.
   Outside it, a crash between the two leaves a count that is permanently
   wrong: nothing recomputes it, because not recomputing it is the fix.
2. It is keyed by the ids **as stored** - the same sanitised spelling the
   event rows get (#1241). A tally filed under a different spelling is a
   count no reader can find, which looks exactly like no tool calls.

Both write paths are exercised, because the previous generation of this bug
(``or "unknown"``, #1241) existed on the COPY path only and every test that
went through ``insert_one`` passed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_domain import tool_call_counts

if TYPE_CHECKING:
    from collections.abc import Sequence

pytestmark = pytest.mark.unit

NUL = chr(0)
_RAW_SESSION = "sess" + NUL + "-1322"
_EXECUTION = "exec-1322"
_TOOL_EVENT = "tool_execution_completed"


class _Conn:
    """Records statements, and whether a transaction was open for each."""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.args: list[tuple[object, ...]] = []
        self.in_transaction_for: list[bool] = []
        self.depth = 0

    def _record(self, query: str, args: tuple[object, ...]) -> None:
        self.statements.append(query)
        self.args.append(args)
        self.in_transaction_for.append(self.depth > 0)

    def transaction(self) -> _Transaction:
        return _Transaction(self)

    async def execute(self, query: str, *args: object) -> str:
        self._record(query, args)
        return "INSERT 0 1"

    async def copy_to_table(self, table: str, **kwargs: object) -> str:
        self._record(f"COPY {table}", (kwargs.get("source"),))
        return "COPY 1"

    @property
    def tally_writes(self) -> list[int]:
        return [i for i, s in enumerate(self.statements) if tool_call_counts.TABLE in s]


class _Transaction:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    async def __aenter__(self) -> None:
        self._conn.depth += 1

    async def __aexit__(self, *_exc: object) -> None:
        self._conn.depth -= 1


class _Acquire:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _Conn:
        return self._conn

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _Pool:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    def acquire(self) -> _Acquire:
        return _Acquire(self._conn)


class _Store:
    """Just enough of AgentEventStore for the two real write functions."""

    def __init__(self, conn: _Conn) -> None:
        self.pool = _Pool(conn)
        self._initialized = True


def _tallied(conn: _Conn) -> list[tuple[object, object, object]]:
    """The (session, execution, count) triples the tally was handed."""
    triples: list[tuple[object, object, object]] = []
    for i in conn.tally_writes:
        sessions, executions, counts = conn.args[i]
        assert isinstance(sessions, list)
        assert isinstance(executions, list)
        assert isinstance(counts, list)
        triples.extend(zip(sessions, executions, counts, strict=True))
    return triples


def _stored_ids(event_type: str) -> tuple[str, str]:
    """What the WRITER makes of the raw ids - asked, not assumed."""
    from syn_adapters.events.models import AgentEvent

    event = AgentEvent(event_type=event_type, session_id=_RAW_SESSION, execution_id=_EXECUTION)
    assert event.session_id is not None
    assert event.execution_id is not None
    return event.session_id, event.execution_id


def _tool_event() -> dict[str, str]:
    return {
        "event_type": _TOOL_EVENT,
        "session_id": _RAW_SESSION,
        "execution_id": _EXECUTION,
        "tool_name": "Bash",
    }


async def test_insert_one_tallies_inside_the_events_transaction() -> None:
    from syn_adapters.events.store_write import insert_one

    conn = _Conn()

    await insert_one(_Store(conn), _tool_event())  # type: ignore[arg-type]  # a recording double

    assert len(conn.tally_writes) == 1
    index = conn.tally_writes[0]
    assert conn.in_transaction_for[index], "the tally was written outside the transaction"
    assert conn.in_transaction_for[0], "the event row was written outside the transaction"
    assert _tallied(conn) == [(*_stored_ids(_TOOL_EVENT), 1)]


async def test_insert_batch_tallies_inside_the_copy_transaction() -> None:
    from syn_adapters.events.store_write import insert_batch

    conn = _Conn()

    written = await insert_batch(_Store(conn), [_tool_event(), _tool_event()])  # type: ignore[arg-type]

    assert written == 1  # what the fake COPY reported; the count is not the point
    assert len(conn.tally_writes) == 1
    assert conn.in_transaction_for[conn.tally_writes[0]]
    # Folded, not one statement per event: a batch is one round trip.
    assert _tallied(conn) == [(*_stored_ids(_TOOL_EVENT), 2)]


@pytest.mark.parametrize("event_type", ["session_started", "token_usage", "tool_execution_started"])
async def test_events_that_are_not_tool_completions_write_no_tally(event_type: str) -> None:
    """``tool_execution_started`` is the one that matters.

    It arrives for every tool call, immediately before the completion, so
    counting it too would double every number on the dashboard.
    """
    from syn_adapters.events.store_write import insert_batch, insert_one

    for write in (
        lambda conn: insert_one(
            _Store(conn), {"event_type": event_type, "session_id": _RAW_SESSION}
        ),  # type: ignore[arg-type]
        lambda conn: insert_batch(
            _Store(conn), [{"event_type": event_type, "session_id": _RAW_SESSION}]
        ),  # type: ignore[arg-type]
    ):
        conn = _Conn()
        await write(conn)
        assert conn.tally_writes == [], f"{event_type} was counted as a tool call"


async def test_a_batch_of_mixed_events_counts_only_its_tool_completions() -> None:
    """The realistic batch: telemetry arrives interleaved, not sorted by type."""
    from syn_adapters.events.store_write import insert_batch

    conn = _Conn()

    await insert_batch(  # type: ignore[arg-type]
        _Store(conn),
        [
            {"event_type": "token_usage", "session_id": _RAW_SESSION},
            _tool_event(),
            {"event_type": "tool_execution_started", "session_id": _RAW_SESSION},
            _tool_event(),
            {"event_type": "session_started", "session_id": _RAW_SESSION},
        ],
    )

    assert _tallied(conn) == [(*_stored_ids(_TOOL_EVENT), 2)]


async def test_a_tool_call_with_no_execution_is_tallied_under_its_session() -> None:
    """The count it replaced had no join, so these rows reached the total."""
    from syn_adapters.events.store_write import insert_one

    conn = _Conn()

    await insert_one(  # type: ignore[arg-type]
        _Store(conn), {"event_type": _TOOL_EVENT, "session_id": _RAW_SESSION}
    )

    sessions: Sequence[object] = [t[0] for t in _tallied(conn)]
    assert sessions == [_stored_ids(_TOOL_EVENT)[0]]
    assert [t[1] for t in _tallied(conn)] == [tool_call_counts.NO_EXECUTION]
