"""A finished tool call has to report how long it took, through the API (#1064).

`ObservabilityCollector.record_tool_completed` writes no `duration_ms`, so the
completion rows the stream processors produce carry none, and every reader that
asks a row for a duration gets `None` - `total_duration_ms` was a constant 0 on
every dashboard. The duration lives in the gap between the two rows a call
writes, which only the reader of a whole result set can see.

So these tests start from rows in the shape `record_tool_completed` really
stores (no `duration_ms` key at all) and assert on the JSON the HTTP endpoints
return, with only asyncpg replaced. Asserting on `ToolOperation` instead would
pass with the projection fixed and the API still reporting zero, which is the
hop this issue is about.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from httpx import ASGITransport, AsyncClient

from syn_adapters.projections.session_tools import SessionToolsProjection
from syn_shared.events import (
    SUBAGENT_STOPPED,
    TOOL_EXECUTION_COMPLETED,
    TOOL_EXECUTION_STARTED,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

pytestmark = pytest.mark.unit

SESSION_ID = "sess-1064"
STARTED_AT = datetime(2026, 3, 4, 12, 0, 0, tzinfo=UTC)
# 1.5s: not a round second, so a wrong unit (1 or 1500000) cannot pass as 1500.
TOOK = timedelta(milliseconds=1500)


def _row(event_type: str, at: datetime, **data: Any) -> dict[str, Any]:
    """One row as the projection's SQL returns it."""
    return {"event_type": event_type, "time": at, "data": data}


def _a_tool_call_that_took(
    took: timedelta, *, tool_use_id: str = "toolu_1", **completed_extra: Any
) -> list[dict[str, Any]]:
    """The two rows one Bash call writes, `took` apart.

    The completion payload is exactly what `record_tool_completed` sends:
    `tool_name`, `tool_use_id`, `success`, `output_preview` - and no duration.
    """
    return [
        _row(
            TOOL_EXECUTION_STARTED,
            STARTED_AT,
            tool_name="Bash",
            tool_use_id=tool_use_id,
            input_preview='{"command": "pytest"}',
        ),
        _row(
            TOOL_EXECUTION_COMPLETED,
            STARTED_AT + took,
            tool_name="Bash",
            tool_use_id=tool_use_id,
            success=True,
            output_preview="ok",
            **completed_extra,
        ),
    ]


class _Connection:
    def __init__(self, rows: Sequence[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetch(self, *_args: object) -> Sequence[dict[str, Any]]:
        return self._rows


class _Acquire:
    def __init__(self, rows: Sequence[dict[str, Any]]) -> None:
        self._rows = rows

    async def __aenter__(self) -> _Connection:
        return _Connection(self._rows)

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _Pool:
    """Stands in for asyncpg only - the projection's own SQL path still runs."""

    def __init__(self, rows: Sequence[dict[str, Any]]) -> None:
        self._rows = rows

    def acquire(self) -> _Acquire:
        return _Acquire(self._rows)


class _Store:
    async def get(self, _namespace: str, _entity_id: str) -> dict[str, str]:
        return {"session_id": SESSION_ID}


class _Manager:
    def __init__(self, rows: Sequence[dict[str, Any]]) -> None:
        self.session_tools = SessionToolsProjection(pool=_Pool(rows))  # type: ignore[arg-type]  # asyncpg stand-in
        self.store = _Store()


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch):
    """Returns a callable: rows in, the parsed body of a GET out."""

    async def get(path: str, rows: Sequence[dict[str, Any]]) -> Any:
        from syn_api.main import create_app

        manager = _Manager(rows)
        for module in ("syn_api.routes.events", "syn_api.routes.observability"):
            monkeypatch.setattr(f"{module}.get_projection_mgr", lambda: manager)

            async def _connected() -> None:
                return None

            monkeypatch.setattr(f"{module}.ensure_connected", _connected)

        transport = ASGITransport(app=create_app())
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(path)
        assert response.status_code == 200, response.text
        return json.loads(response.text)

    return get


@pytest.mark.asyncio
async def test_tool_summary_reports_the_time_the_call_actually_took(api: Any) -> None:
    """`GET /events/sessions/{id}/tools` - the endpoint the issue names.

    1.5s of Bash must arrive as 1500ms of Bash. Before the fix this was 0.0,
    because the only rows that reach the accumulator carry no duration.
    """
    body = await api(f"/events/sessions/{SESSION_ID}/tools", _a_tool_call_that_took(TOOK))

    (bash,) = [t for t in body if t["tool_name"] == "Bash"]
    assert bash["call_count"] == 1
    assert bash["total_duration_ms"] == 1500
    assert bash["avg_duration_ms"] == 1500.0


@pytest.mark.asyncio
async def test_the_timeline_entry_for_the_completion_carries_its_duration(api: Any) -> None:
    """`GET /observability/sessions/{id}/tools` - the per-call read of the same rows.

    The start row still has no duration: nothing has finished at that point,
    and inventing one there would make every unfinished call look instant.
    """
    body = await api(f"/observability/sessions/{SESSION_ID}/tools", _a_tool_call_that_took(TOOK))

    by_type = {e["operation_type"]: e for e in body["executions"]}
    assert by_type[TOOL_EXECUTION_COMPLETED]["duration_ms"] == 1500
    assert by_type[TOOL_EXECUTION_STARTED]["duration_ms"] is None


@pytest.mark.asyncio
async def test_a_duration_the_producer_measured_itself_is_not_overwritten(api: Any) -> None:
    """The collector's hook path times the call at the source and sends it.

    That number beats the gap between two writes, so a payload that carries
    one must come back unchanged - here 250ms, against rows 1.5s apart.
    """
    rows = _a_tool_call_that_took(TOOK, duration_ms=250)

    body = await api(f"/events/sessions/{SESSION_ID}/tools", rows)

    (bash,) = [t for t in body if t["tool_name"] == "Bash"]
    assert bash["total_duration_ms"] == 250


@pytest.mark.asyncio
async def test_a_completion_with_no_start_in_the_result_reports_no_duration(api: Any) -> None:
    """Codex supports a completion whose start never arrived (truncated stream).

    There is nothing to measure from, so the summary must stay at 0 rather
    than measure from some other call's start - a wrong number here is worse
    than the missing one, because nothing downstream can tell it apart.
    """
    rows = _a_tool_call_that_took(TOOK)[1:]

    body = await api(f"/events/sessions/{SESSION_ID}/tools", rows)

    (bash,) = [t for t in body if t["tool_name"] == "Bash"]
    assert bash["call_count"] == 1
    assert bash["total_duration_ms"] == 0


@pytest.mark.asyncio
async def test_a_subagent_call_is_timed_under_the_name_it_is_relabelled_to(api: Any) -> None:
    """An Agent/Task call's two rows are rewritten to subagent_started/_stopped.

    The rewrite happens before any reader sees them, so a pairing that only
    knew the tool_execution_* types would leave every delegation untimed -
    the rows it needs are there, under other names.
    """
    delegated = [
        _row(
            TOOL_EXECUTION_STARTED,
            STARTED_AT,
            tool_name="Task",
            tool_use_id="toolu_sub",
            input_preview='{"description": "review the diff"}',
        ),
        _row(
            TOOL_EXECUTION_COMPLETED,
            STARTED_AT + TOOK,
            tool_name="Task",
            tool_use_id="toolu_sub",
            success=True,
            output_preview="reviewed",
        ),
    ]

    body = await api(f"/observability/sessions/{SESSION_ID}/tools", delegated)

    (stopped,) = [e for e in body["executions"] if e["operation_type"] == SUBAGENT_STOPPED]
    assert stopped["duration_ms"] == 1500
