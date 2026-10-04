"""Parity: E2 changes how the five pages are read, never what they say.

E2 made two changes to the read paths behind /executions, /executions/{id},
/sessions, /sessions/{id} and /artifacts:

1. Lane 2 reads of ``agent_events`` are bounded to the UTC days their ids have
   telemetry on (``syn_domain.agent_event_span``).
2. List pages scan only the fields their predicates read, then load whole
   documents for the page (``syn_domain.projection_scan``), with a lean column
   on ``artifact_summaries``.

Each is claimed to return exactly what the old read returned. This test holds
them to it on the gate's seed - compressed chunks, 240 days - plus the edge
cases the claims are most likely to be wrong about: an execution whose
telemetry spans several days and crosses a chunk boundary, documents with no
timestamp (counted into ``excluded_undated`` under a window), filters pushed
to the store, search, tags, facets, a page past the first. Every response is
fetched twice, once through the E2 paths and once with both switched back to
the old reads, and compared whole: every field, every row, in order.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, tzinfo
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import pytest

from . import test_list_detail_latency_budget as gate

if TYPE_CHECKING:
    import httpx

pytestmark = pytest.mark.integration

MULTI_DAY_EXECUTION = 10
DETAIL_EXECUTIONS = (0, 1, MULTI_DAY_EXECUTION, 7, gate.DETAIL_EXECUTION, 1999)
TIED = 30


@runtime_checkable
class _NeverScans(Protocol):
    """A protocol no store satisfies, so ``paginate_projection`` takes the old read."""

    def e2_parity_never_implemented(self) -> None: ...


def _requests(now: datetime) -> list[tuple[str, dict[str, str]]]:
    window_after = (now - timedelta(days=30)).isoformat()
    window_before = (now - timedelta(days=5)).isoformat()
    requests: list[tuple[str, dict[str, str]]] = [
        ("/executions", {"page_size": "50"}),
        ("/executions", {"page_size": "20"}),
        ("/executions", {"page": "2", "page_size": "20"}),
        ("/executions", {"page": "3", "page_size": "50"}),
        ("/executions", {"statuses": "running", "page_size": "50"}),
        ("/executions", {"q": "wf-1", "page_size": "50"}),
        ("/executions", {"tag": "gate", "page": "2", "page_size": "25"}),
        (
            "/executions",
            {"started_after": window_after, "started_before": window_before, "page_size": "50"},
        ),
        ("/sessions", {"page_size": "20"}),
        ("/sessions", {"page": "2", "page_size": "20"}),
        ("/sessions", {"page": "2", "page_size": "50"}),
        ("/sessions", {"execution_id": gate.execution_id(MULTI_DAY_EXECUTION)}),
        ("/sessions", {"workflow_id": gate.workflow_id(3), "page_size": "50"}),
        ("/sessions", {"q": "sess-0004", "statuses": "completed,failed"}),
        ("/sessions", {"started_after": window_after, "started_before": window_before}),
        ("/artifacts", {"page_size": "20"}),
        ("/artifacts", {"page": "2", "page_size": "20"}),
        ("/artifacts", {"page": "4", "page_size": "50"}),
        ("/artifacts", {"execution_id": gate.execution_id(MULTI_DAY_EXECUTION)}),
        ("/artifacts", {"artifact_type": "plan", "page_size": "50"}),
        ("/artifacts", {"q": "phase 2", "page_size": "50"}),
        ("/artifacts", {"created_after": window_after, "created_before": window_before}),
    ]
    requests += [(f"/executions/{gate.execution_id(n)}", {}) for n in DETAIL_EXECUTIONS]
    requests += [
        (f"/sessions/{gate.session_id(n, phase)}", {})
        for n in (0, MULTI_DAY_EXECUTION, gate.DETAIL_EXECUTION)
        for phase in range(gate.PHASES)
    ]
    return requests


async def _add_edge_cases(now: datetime) -> None:
    """What the seed does not already cover, written the way production writes it."""
    from syn_adapters.events import store_helpers
    from syn_adapters.projection_stores import get_projection_store

    store = get_projection_store()
    # Telemetry for one execution spread over three more days - more chunks,
    # including the uncompressed one - so its span is wider than one day and
    # its rows sit on both sides of a chunk boundary.
    pool = store_helpers._event_store.pool  # type: ignore[union-attr]  # set by the fixture
    assert pool is not None
    execution = gate.execution_id(MULTI_DAY_EXECUTION)
    session = gate.session_id(MULTI_DAY_EXECUTION, 2)
    turn = json.dumps({"model": "claude-opus-5", "input_tokens": 11, "output_tokens": 3})
    later = [
        (now - timedelta(days=days, minutes=1), gate.TOKEN_USAGE, session, execution, "p2", turn)
        for days in (3, 2, 0)
    ]
    async with pool.acquire() as conn:
        await conn.copy_records_to_table("agent_events", records=later, columns=gate._COLUMNS)
    # Ties: more rows sharing one timestamp than a page holds, newest of all,
    # so the tie straddles the first page boundary and only a total order
    # decides which of them land on it. None has telemetry, so the page's
    # span lookup mixes ids the rollup knows with ids it has never seen.
    tied = (now + timedelta(minutes=5)).isoformat()
    for n in range(TIED):
        await store.save(
            "session_summaries",
            f"sess-tied-{n:02d}",
            {
                "id": f"sess-tied-{n:02d}",
                "workflow_id": gate.workflow_id(n),
                "execution_id": gate.execution_id(n),
                "status": "running",
                "agent_type": "claude",
                "started_at": tied,
            },
        )
        await store.save(
            "artifact_summaries",
            f"art-tied-{n:02d}",
            {
                "id": f"art-tied-{n:02d}",
                "workflow_id": gate.workflow_id(n),
                "execution_id": gate.execution_id(n),
                "phase_id": "p0",
                "artifact_type": "report",
                "name": f"Tied {n}",
                "created_at": tied,
                "size_bytes": 4,
                "content": "tied",
            },
        )
        await store.save(
            "workflow_executions",
            f"exec-tied-{n:02d}",
            {
                "workflow_execution_id": f"exec-tied-{n:02d}",
                "workflow_id": gate.workflow_id(n),
                "workflow_name": "Tied",
                "status": "running",
                "started_at": tied,
                "total_phases": 1,
            },
        )
    # Undated documents: excluded from a windowed page and counted as such.
    await store.save(
        "artifact_summaries",
        "art-undated",
        {
            "id": "art-undated",
            "workflow_id": gate.workflow_id(1),
            "execution_id": gate.execution_id(1),
            "phase_id": "p0",
            "artifact_type": "plan",
            "name": "Undated plan",
            "created_at": None,
            "size_bytes": 5,
            "content": "hello",
        },
    )
    await store.save(
        "session_summaries",
        "sess-undated",
        {
            "id": "sess-undated",
            "workflow_id": gate.workflow_id(1),
            "execution_id": gate.execution_id(1),
            "status": "failed",
            "agent_type": "claude",
            "started_at": None,
        },
    )


async def _fetch_all(
    client: httpx.AsyncClient, requests: list[tuple[str, dict[str, str]]]
) -> list[object]:
    out: list[object] = []
    for path, params in requests:
        response = await client.get(path, params=params)
        assert response.status_code == 200, (path, params, response.text)
        out.append(response.json())
    return out


async def test_e2_read_paths_answer_exactly_what_the_old_ones_did(
    e2_seeded_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from syn_domain import agent_event_span, projection_scan
    from syn_domain.agent_event_span import EventSpan

    client = e2_seeded_client
    now = datetime.now(UTC).replace(microsecond=0)
    await _add_edge_cases(now)
    requests = _requests(now)

    # Running executions and sessions report a duration against the wall
    # clock, so both passes must see the same clock.
    frozen = now + timedelta(minutes=1)

    class _FrozenClock(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]  # a fixed instant
            return frozen if tz is not None else frozen.replace(tzinfo=None)

    monkeypatch.setattr("syn_shared.display.formatters.datetime", _FrozenClock)

    e2 = await _fetch_all(client, requests)

    async def unbounded(_conn: object, _ids: object) -> EventSpan:
        return EventSpan.unbounded()

    with monkeypatch.context() as old:
        old.setattr(agent_event_span, "for_sessions", unbounded)
        old.setattr(agent_event_span, "for_executions", unbounded)
        old.setattr(projection_scan, "ProjectionFieldScan", _NeverScans)
        before = await _fetch_all(client, requests)

    # The edge cases are really in play, or the comparison proves nothing.
    windowed = [
        answer
        for (path, params), answer in zip(requests, e2, strict=True)
        if path in ("/sessions", "/artifacts") and any("_after" in key for key in params)
    ]
    assert len(windowed) == 2, windowed
    assert all(isinstance(w, dict) and w["excluded_undated"] >= 1 for w in windowed), windowed

    mismatched = [
        (path, params)
        for (path, params), new, old_answer in zip(requests, e2, before, strict=True)
        if new != old_answer
    ]
    assert not mismatched, f"E2 changed the answer for {mismatched}"


async def test_the_span_and_the_reads_it_bounds_share_one_snapshot(e2_database: str) -> None:
    """An event committed on a NEW day between the span lookup and the read.

    Under READ COMMITTED the bounded read would miss it while an unbounded
    read saw it. ``custom_plans`` is one REPEATABLE READ snapshot, so both
    reads answer for the same instant - the instant the snapshot was taken.
    """
    from syn_adapters.events import AgentEventStore
    from syn_domain import agent_event_span

    store = AgentEventStore(e2_database)
    await store.initialize()
    pool = store.pool
    assert pool is not None
    session = "sess-snapshot"
    old_day = datetime.now(UTC) - timedelta(days=3)
    row = (old_day, gate.TOKEN_USAGE, session, "exec-snapshot", "p0", "{}")
    count_sql = (
        "SELECT COUNT(*) FROM agent_events WHERE session_id = $1 AND time >= $2 AND time < $3"
    )
    try:
        async with pool.acquire() as conn:
            await conn.copy_records_to_table("agent_events", records=[row], columns=gate._COLUMNS)
        async with pool.acquire() as reader, agent_event_span.custom_plans(reader):  # type: ignore[arg-type]  # asyncpg proxy
            span = await agent_event_span.for_sessions(reader, [session])  # type: ignore[arg-type]
            async with pool.acquire() as writer:
                await writer.copy_records_to_table(
                    "agent_events",
                    records=[(datetime.now(UTC), *row[1:])],
                    columns=gate._COLUMNS,
                )
            bounded = await reader.fetchval(count_sql, session, span.lower, span.upper)
            everything = await reader.fetchval(
                count_sql,
                session,
                agent_event_span.UNBOUNDED_LOWER,
                agent_event_span.UNBOUNDED_UPPER,
            )
        assert bounded == everything == 1
        async with pool.acquire() as conn:
            assert (
                await conn.fetchval(
                    "SELECT COUNT(*) FROM agent_events WHERE session_id = $1", session
                )
                == 2
            )
    finally:
        await store.close()
