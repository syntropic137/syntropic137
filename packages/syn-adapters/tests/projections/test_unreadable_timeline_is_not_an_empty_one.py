"""A timeline that could not be read is not a session that recorded nothing (#1332).

`SessionToolsProjection.get` answered `[]` three ways: for a session with no
rows, for a process with no database to ask, and for a query that died. The
three are not the same fact, and one reader downstream measures a phase from
them - `phases[].activity`, which exists to tell a phase killed on its deadline
from one that hung. Fed an empty list it reports no operations and no push,
which is precisely how a stalled phase reads, and "stalled" is the verdict that
tells an operator not to pay for the run again. So a telemetry outage produced,
out of nothing, the most expensive reading the system can serve.

`None` is now the answer for "could not read" and `[]` keeps its one meaning.
The tests here are the two failure branches; the paired assertion that a
genuine empty still reports zero is at the far end of the read path, in
syn-api's `test_timeout_vs_stall_signals.py`, because that is where the
difference is acted on.
"""

from __future__ import annotations

import pytest

from syn_adapters.projections.session_tools import SessionToolsProjection

pytestmark = pytest.mark.unit

SESSION_ID = "sess-1332"


class _DeadAcquire:
    async def __aenter__(self) -> object:
        raise RuntimeError("connection reset by peer")

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _DeadPool:
    """An asyncpg pool that fails on use - a reset link, a full connection pool.

    Stands in for asyncpg only: the projection's own query path still runs, so
    the failure happens where a real one does rather than at a mock boundary.
    """

    def acquire(self) -> _DeadAcquire:
        return _DeadAcquire()


@pytest.mark.anyio
async def test_no_database_answers_unknown_rather_than_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With nothing to query, the projection must not answer for the session.

    The lazy pool lookup is made to fail the way it does before the event store
    is up, or in a process that has no observability database configured at
    all. That is a normal state, not an error - which is exactly why it was
    dangerous: the read succeeded and said the session did nothing.
    """

    def _no_store() -> object:
        raise RuntimeError("SYN_OBSERVABILITY_DB_URL must be configured")

    monkeypatch.setattr("syn_adapters.events.get_event_store", _no_store)

    assert await SessionToolsProjection(pool=None).get(SESSION_ID) is None


@pytest.mark.anyio
async def test_a_query_that_dies_answers_unknown_rather_than_empty() -> None:
    """The read still fails soft - Lane 2 is telemetry, not domain truth.

    Soft is not silent, though. The caller is told the query failed by getting
    `None` back, and what it must not be told is that the session is empty.
    """
    projection = SessionToolsProjection(pool=_DeadPool())  # type: ignore[arg-type]  # asyncpg stand-in

    assert await projection.get(SESSION_ID) is None
