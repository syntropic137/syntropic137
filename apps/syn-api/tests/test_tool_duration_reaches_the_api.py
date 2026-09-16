"""A finished tool call has to report how long it took, through the API (#1064).

`ObservabilityCollector.record_tool_completed` writes no `duration_ms`, so the
completion rows the stream processors produce carry none, and every reader that
asks a row for a duration gets `None` - `total_duration_ms` was a constant 0 on
every dashboard. The duration lives in the gap between the two rows a call
writes, which only a reader of the whole result set can see.

So these tests start from rows in the shape `record_tool_completed` really
stores (no `duration_ms` key at all) and assert on the JSON the HTTP endpoints
return, with only asyncpg replaced. Asserting on `ToolOperation` instead would
pass with the projection fixed and the API still reporting zero, which is the
hop this issue is about.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from syn_adapters.projections.session_tools import SessionToolsProjection
from syn_shared.events import (
    SUBAGENT_STOPPED,
    TOOL_EXECUTION_COMPLETED,
    TOOL_EXECUTION_STARTED,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from httpx import Response

    #: Rows in, the response from a GET against the real app out.
    ApiGet = Callable[[str, "Sequence[_Row]"], Awaitable[Response]]

pytestmark = pytest.mark.unit

SESSION_ID = "sess-1064"
STARTED_AT = datetime(2026, 3, 4, 12, 0, 0, tzinfo=UTC)
# 1.5s: not a round second, so a wrong unit (1, or 1500000) cannot pass as 1500.
TOOK = timedelta(milliseconds=1500)

_PayloadValue = str | bool | int


@dataclass(frozen=True)
class _Payload:
    """An observation payload, holding only the keys its producer sets.

    `record_tool_completed` sends four of these and no duration, which is the
    whole of #1064; `duration_ms` is here because the collector's hook path
    does send one, and the two cases have to be told apart.
    """

    tool_name: str
    tool_use_id: str
    input_preview: str | None = None
    success: bool | None = None
    output_preview: str | None = None
    duration_ms: int | None = None

    def stored(self) -> dict[str, _PayloadValue]:
        """The payload as the store holds it: an unset key is absent, not null.

        The projection reads with `data.get(...)`, so a key present and null
        is a different input from a key that was never written.
        """
        written: dict[str, _PayloadValue] = {}
        for name, value in vars(self).items():
            if value is not None:
                written[name] = value
        return written


@dataclass(frozen=True)
class _Row:
    """A row shaped like the `asyncpg.Record` the projection's SQL returns."""

    event_type: str
    time: datetime
    payload: _Payload

    def __getitem__(self, column: str) -> str | datetime | dict[str, _PayloadValue]:
        """A Record is read by column name, and the projection reads it that way."""
        if column == "data":
            return self.payload.stored()
        if column == "event_type":
            return self.event_type
        return self.time


def _a_tool_call_that_took(
    took: timedelta,
    *,
    tool_name: str = "Bash",
    tool_use_id: str = "toolu_1",
    measured_by_producer: int | None = None,
) -> list[_Row]:
    """The two rows one tool call writes, `took` apart."""
    return [
        _Row(
            TOOL_EXECUTION_STARTED,
            STARTED_AT,
            _Payload(
                tool_name=tool_name,
                tool_use_id=tool_use_id,
                input_preview='{"command": "pytest"}',
            ),
        ),
        _Row(
            TOOL_EXECUTION_COMPLETED,
            STARTED_AT + took,
            _Payload(
                tool_name=tool_name,
                tool_use_id=tool_use_id,
                success=True,
                output_preview="ok",
                duration_ms=measured_by_producer,
            ),
        ),
    ]


class _Connection:
    def __init__(self, rows: Sequence[_Row]) -> None:
        self._rows = rows

    async def fetch(self, *_args: object) -> Sequence[_Row]:
        return self._rows


class _Acquire:
    def __init__(self, rows: Sequence[_Row]) -> None:
        self._rows = rows

    async def __aenter__(self) -> _Connection:
        return _Connection(self._rows)

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _Pool:
    """Stands in for asyncpg only - the projection's own query path still runs."""

    def __init__(self, rows: Sequence[_Row]) -> None:
        self._rows = rows

    def acquire(self) -> _Acquire:
        return _Acquire(self._rows)


class _Store:
    """Resolves the session id exactly, so prefix resolution is not the subject."""

    async def get(self, _namespace: str, _entity_id: str) -> dict[str, str]:
        return {"session_id": SESSION_ID}


class _Manager:
    def __init__(self, rows: Sequence[_Row]) -> None:
        self.session_tools = SessionToolsProjection(pool=_Pool(rows))  # type: ignore[arg-type]  # asyncpg stand-in
        self.store = _Store()


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> ApiGet:
    """Serves the given rows to the real app, and returns what it answers."""

    async def get(path: str, rows: Sequence[_Row]) -> Response:
        from syn_api.main import create_app

        manager = _Manager(rows)

        async def _connected() -> None:
            return None

        for module in ("syn_api.routes.events", "syn_api.routes.observability"):
            monkeypatch.setattr(f"{module}.get_projection_mgr", lambda: manager)
            monkeypatch.setattr(f"{module}.ensure_connected", _connected)

        transport = ASGITransport(app=create_app())
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(path)
        assert response.status_code == 200, response.text
        return response

    return get


@pytest.mark.asyncio
async def test_tool_summary_reports_the_time_the_call_actually_took(api: ApiGet) -> None:
    """`GET /events/sessions/{id}/tools` - the endpoint the issue names.

    1.5s of Bash must arrive as 1500ms of Bash. Before the fix this was 0,
    because the only rows reaching the accumulator carry no duration.
    """
    response = await api(f"/events/sessions/{SESSION_ID}/tools", _a_tool_call_that_took(TOOK))

    (bash,) = [tool for tool in response.json() if tool["tool_name"] == "Bash"]
    assert bash["call_count"] == 1
    assert bash["total_duration_ms"] == 1500
    assert bash["avg_duration_ms"] == 1500.0


@pytest.mark.asyncio
async def test_the_timeline_entry_for_the_completion_carries_its_duration(api: ApiGet) -> None:
    """`GET /observability/sessions/{id}/tools` - the per-call read of the same rows.

    The start row still reports none: nothing has finished at that point, and
    a number there would make every unfinished call look instant.
    """
    response = await api(
        f"/observability/sessions/{SESSION_ID}/tools", _a_tool_call_that_took(TOOK)
    )

    by_type = {entry["operation_type"]: entry for entry in response.json()["executions"]}
    assert by_type[TOOL_EXECUTION_COMPLETED]["duration_ms"] == 1500
    assert by_type[TOOL_EXECUTION_STARTED]["duration_ms"] is None


@pytest.mark.asyncio
async def test_a_duration_the_producer_measured_itself_is_not_overwritten(api: ApiGet) -> None:
    """The collector's hook path times the call at the source and sends it.

    That number beats the gap between two writes, so a payload carrying one
    must come back unchanged - here 250ms, from rows 1.5s apart.
    """
    rows = _a_tool_call_that_took(TOOK, measured_by_producer=250)

    response = await api(f"/events/sessions/{SESSION_ID}/tools", rows)

    (bash,) = [tool for tool in response.json() if tool["tool_name"] == "Bash"]
    assert bash["total_duration_ms"] == 250


@pytest.mark.asyncio
async def test_a_completion_with_no_start_in_the_result_reports_no_duration(api: ApiGet) -> None:
    """Codex supports a completion whose start never arrived (truncated stream).

    There is nothing to measure from, so the summary stays at 0 rather than
    measure from some other call's start: a wrong number here is worse than
    the missing one, because nothing downstream can tell it apart.
    """
    completion_only = _a_tool_call_that_took(TOOK)[1:]

    response = await api(f"/events/sessions/{SESSION_ID}/tools", completion_only)

    (bash,) = [tool for tool in response.json() if tool["tool_name"] == "Bash"]
    assert bash["call_count"] == 1
    assert bash["total_duration_ms"] == 0


@pytest.mark.asyncio
async def test_a_subagent_call_is_timed_under_the_name_it_is_relabelled_to(api: ApiGet) -> None:
    """An Agent/Task call's rows are rewritten to subagent_started/_stopped.

    The rewrite happens before any reader sees them, so a pairing that knew
    only the tool_execution_* types would leave every delegation untimed -
    the rows it needs are there, under other names.
    """
    delegated = _a_tool_call_that_took(TOOK, tool_name="Task", tool_use_id="toolu_sub")

    response = await api(f"/observability/sessions/{SESSION_ID}/tools", delegated)

    (stopped,) = [
        entry
        for entry in response.json()["executions"]
        if entry["operation_type"] == SUBAGENT_STOPPED
    ]
    assert stopped["duration_ms"] == 1500
