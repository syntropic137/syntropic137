"""The time range an id's telemetry occupies, so a hypertable read can skip the rest.

WHY THIS EXISTS (E2). Every Lane 2 read behind the executions, sessions and
execution-detail pages filters ``agent_events`` on a session or execution id
and nothing else. ``agent_events`` is a hypertable with one chunk per day, and
a predicate that names no time cannot exclude a chunk, so the PLANNER has to
open every chunk of all history - and, for a compressed one, its compressed
twin as well - before it can run anything. Measured on the E2 latency gate's
seed (241 daily chunks): one execution-keyed read planned in 30-50ms and ran in
under 5; the session timeline's self-join planned in 120ms; the execution
detail page issued fifteen such reads and spent ~900ms of its ~1.1s planning.
It grows with every day of history, which is why the live install, with more
of it, took seconds.

THE FIX IS THE SAME QUERY WITH A TIME BOUND. ``agent_event_day_rollup``
(#1253) already records, for every (UTC day, session, execution) triple, that
an event exists. Every event of an id therefore lies inside

    [first day 00:00 UTC, last day + 1 00:00 UTC)

so adding that range to a read changes no row it returns, and lets the planner
exclude every other chunk. The bounds are bound as PARAMETERS rather than
written as a subquery: a constant is what plan-time chunk exclusion can use,
and a subquery bound is not (measured: 140ms of planning with it, 4.6ms with
the constants).

WHAT IT RELIES ON. That the day rollup is complete - the same thing the
contribution heatmap already relies on, and what ``EventStoreSchema.validate``
refuses to start without (table, live trigger). The trigger writes the rollup
row in the same transaction as the event, so no committed event lacks one.

An id the rollup has never seen gets the UNBOUNDED span, never an empty one:
the read then runs exactly as it did before this module existed. Absent is not
evidence of "no events", only of "nothing to narrow by".

PLANNED FOR THESE BOUNDS, EVERY TIME. asyncpg prepares each statement and
PostgreSQL may switch a prepared statement to a GENERIC plan after five runs.
A generic plan cannot see the bounds, so building one opens every chunk again
(measured: /sessions p95 372ms with the switch, 88ms without), and it is the
same trap E1 found in the heatmap. Bounded reads therefore run inside
:func:`custom_plans`, which pins ``plan_cache_mode = force_custom_plan`` for
one transaction.

A RACE THAT CHANGES NOTHING. The span is read, then the bounded query runs. An
event committed between the two on a NEW day falls outside the span; that is
the same answer the read would have given a moment earlier, which is all two
separate statements ever promised. Events on a day already in the span are
inside it.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence


class SpanRow(Protocol):
    """A result row, read by column name."""

    def __getitem__(self, key: str, /) -> object: ...


class SpanConnection(Protocol):
    """The one thing the span lookup needs from a connection. asyncpg satisfies it."""

    async def fetch(self, query: str, /, *args: object) -> Sequence[SpanRow]: ...


class SpanTransaction(Protocol):
    """An open transaction, released when the block exits."""

    async def __aenter__(self) -> object: ...

    async def __aexit__(self, exc_type: object, exc: object, tb: object, /) -> object: ...


class PlanningConnection(Protocol):
    """What :func:`custom_plans` needs from a connection. asyncpg satisfies it."""

    async def execute(self, query: str, /, *args: object) -> str: ...

    def transaction(self) -> SpanTransaction: ...


#: Bounds that admit every row: ``time`` is NOT NULL and a timestamptz, and no
#: event is written before year 1 or after 9999. Used instead of NULL so the
#: bounded query has one shape and never needs an ``IS NULL OR`` branch the
#: planner would have to fold before it could exclude a chunk.
UNBOUNDED_LOWER = datetime(1, 1, 1, tzinfo=UTC)
UNBOUNDED_UPPER = datetime(9999, 12, 31, tzinfo=UTC)


@dataclass(frozen=True)
class EventSpan:
    """``[lower, upper)``: every ``agent_events.time`` the ids' rows can carry."""

    lower: datetime
    """Inclusive."""

    upper: datetime
    """Exclusive."""

    @classmethod
    def unbounded(cls) -> EventSpan:
        """The span that excludes nothing: what a read had before E2."""
        return cls(UNBOUNDED_LOWER, UNBOUNDED_UPPER)

    @classmethod
    def of_days(cls, first: date, last: date) -> EventSpan:
        """The UTC days ``first`` through ``last``, both whole."""
        return cls(
            datetime.combine(first, time.min, tzinfo=UTC),
            datetime.combine(last + timedelta(days=1), time.min, tzinfo=UTC),
        )


_SESSION_DAYS_SQL = """
SELECT MIN(day) AS first_day, MAX(day) AS last_day
FROM agent_event_day_rollup
WHERE session_id = ANY($1::text[])
"""

_EXECUTION_DAYS_SQL = """
SELECT MIN(day) AS first_day, MAX(day) AS last_day
FROM agent_event_day_rollup
WHERE execution_id = ANY($1::text[])
"""


async def for_sessions(conn: SpanConnection, session_ids: Sequence[str]) -> EventSpan:
    """The span covering every event of these sessions (ids as stored)."""
    return await _span(conn, _SESSION_DAYS_SQL, session_ids)


async def for_executions(conn: SpanConnection, execution_ids: Sequence[str]) -> EventSpan:
    """The span covering every event of these executions (ids as stored)."""
    return await _span(conn, _EXECUTION_DAYS_SQL, execution_ids)


async def _span(conn: SpanConnection, sql: str, ids: Sequence[str]) -> EventSpan:
    if not ids:
        return EventSpan.unbounded()
    rows = await conn.fetch(sql, list(ids))
    first = rows[0]["first_day"] if rows else None
    last = rows[0]["last_day"] if rows else None
    if not isinstance(first, date) or not isinstance(last, date):
        return EventSpan.unbounded()
    return EventSpan.of_days(first, last)


@asynccontextmanager
async def custom_plans(conn: PlanningConnection) -> AsyncIterator[None]:
    """Plan every statement in the block for its own parameters.

    One transaction with ``SET LOCAL plan_cache_mode = force_custom_plan``, so
    a bounded read is always planned with its bounds as constants and the
    planner excludes the chunks outside them. ``SET LOCAL`` ends with the
    transaction, so a pooled connection goes back as it came. Reads only: each
    statement still takes its own snapshot under READ COMMITTED, exactly as it
    did outside a transaction.
    """
    async with conn.transaction():
        await conn.execute("SET LOCAL plan_cache_mode = force_custom_plan")
        yield
