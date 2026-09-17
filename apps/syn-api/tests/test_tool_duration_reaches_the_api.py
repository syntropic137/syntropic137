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

The reverse also has to hold, and the rest of the file is that: a number the
rows do not support must not be reported. A codex `file_change` used to be
recorded as a start and a completion written back-to-back from the single
event that says the change has already happened, so the "duration" was the gap
between our own two writes; and a redelivered completion used to be paired
against a start already consumed by the first delivery. Both produced a
number with the shape of a measurement and none of the content, which is the
same defect as the constant zero, wearing a plausible value.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from syn_adapters.projections.session_tools import SessionToolsProjection
from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    CodexStreamProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)
from syn_shared.codex_stream import CODEX_TOOL_NAME_FILE_CHANGE
from syn_shared.events import (
    SUBAGENT_STOPPED,
    TOOL_EXECUTION_COMPLETED,
    TOOL_EXECUTION_STARTED,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Sequence

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


@pytest.mark.asyncio
async def test_a_redelivered_completion_reports_nothing_rather_than_the_wait(
    api: ApiGet,
) -> None:
    """The same completion, stored twice, must not report the gap to its repeat.

    Delivery is at-least-once and `agent_events` has no uniqueness constraint,
    so a redelivered completion becomes a second row; re-recording re-stamps
    it with `datetime.now(UTC)`, so it lands whenever the redelivery happened -
    here 30s after the call started, for a call that took 1.5s. Paired against
    the start that was still open, the repeat claimed 30000ms: not a missing
    number a reader has to handle, but a wrong one they have no way to doubt.

    A start belongs to one completion and is consumed by it, so the repeat has
    nothing to measure from and says so.
    """
    call = _a_tool_call_that_took(TOOK)
    redelivered = _Row(
        call[1].event_type,
        STARTED_AT + timedelta(seconds=30),
        call[1].payload,
    )

    response = await api(f"/observability/sessions/{SESSION_ID}/tools", [*call, redelivered])

    timed = [
        entry["duration_ms"]
        for entry in response.json()["executions"]
        if entry["operation_type"] == TOOL_EXECUTION_COMPLETED
    ]
    assert timed == [1500, None]


@pytest.mark.asyncio
async def test_a_redelivered_completion_does_not_inflate_the_summary(api: ApiGet) -> None:
    """The same rows through the summary endpoint: 1.5s of Bash, once.

    `_accumulate_tool_stats` adds a call's duration once, so the repeat could
    only have been counted if it arrived first - but it is the number on the
    row that a dashboard shows next to the call, and this pins that the two
    endpoints agree about it.
    """
    call = _a_tool_call_that_took(TOOK)
    redelivered = _Row(call[1].event_type, STARTED_AT + timedelta(seconds=30), call[1].payload)

    response = await api(f"/events/sessions/{SESSION_ID}/tools", [*call, redelivered])

    (bash,) = [tool for tool in response.json() if tool["tool_name"] == "Bash"]
    assert bash["call_count"] == 1
    assert bash["total_duration_ms"] == 1500


#: Real `codex exec --json` captures, shared with the processor's own tests
#: rather than hand-rolled: what a producer records is only worth asserting
#: against input the harness really emitted.
_CODEX_FIXTURES = Path(__file__).resolve().parents[3] / "packages/syn-domain/tests/fixtures/codex"


class _CodexRows:
    """The rows the codex processor writes, in the order it writes them.

    Implements the recorder protocol `CodexStreamProcessor` records through,
    and stores each call in the shape `ObservabilityCollector` gives it - so
    what reaches the projection here is the producer's own decision about
    which rows a call produces, which is the subject of the `file_change` half
    of #1064. (`test_tool_execution_identity.py` drives the real
    `ObservabilityCollector` over the same captures, so that hop is pinned
    too.)

    Rows are stamped `TOOK` apart in write order. That is deliberately far
    apart: a pair written from a single event is microseconds apart in
    production, which rounds to a number small enough to be mistaken for a
    fast call. Spacing the rows makes the difference between a real pair and a
    manufactured one impossible to miss - a manufactured one reports 1500ms
    here.
    """

    def __init__(self) -> None:
        self.rows: list[_Row] = []

    async def record_tool_started(
        self, tool_name: str, tool_use_id: str, input_preview: str
    ) -> None:
        self._append(
            TOOL_EXECUTION_STARTED,
            _Payload(tool_name=tool_name, tool_use_id=tool_use_id, input_preview=input_preview),
        )

    async def record_tool_completed(
        self, tool_name: str, tool_use_id: str, success: bool, output_preview: str | None
    ) -> None:
        self._append(
            TOOL_EXECUTION_COMPLETED,
            _Payload(
                tool_name=tool_name,
                tool_use_id=tool_use_id,
                success=success,
                output_preview=output_preview,
            ),
        )

    async def record_token_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_creation: int = 0,
        cache_read: int = 0,
    ) -> None:
        """Lane-2 telemetry the timeline query excludes; not a row here."""

    async def record_session_summary(
        self,
        total_cost_usd: float | None,
        input_tokens: int,
        output_tokens: int,
        cache_creation: int,
        cache_read: int,
        num_turns: int | None,
        duration_ms: int | None,
        totals_are_authoritative: bool = True,
    ) -> None:
        """Same - a session-level summary is not a tool row."""

    def _append(self, event_type: str, payload: _Payload) -> None:
        self.rows.append(_Row(event_type, STARTED_AT + len(self.rows) * TOOK, payload))


class _NoopWorkspace:
    last_stream_exit_code = 0

    async def interrupt(self) -> bool:
        return True


async def _rows_codex_wrote(capture: str) -> list[_Row]:
    """Run the real processor over a real capture and keep the rows it wrote."""
    recorder = _CodexRows()
    processor = CodexStreamProcessor(
        tokens=TokenAccumulator(),
        collector=recorder,
        controller=None,
        execution_id="exec-1",
        phase_id="phase-1",
        session_id=SESSION_ID,
        agent_model="gpt-5.6",
        rollout=None,
    )

    async def lines() -> AsyncIterator[str]:
        for line in (_CODEX_FIXTURES / capture).read_text().splitlines():
            yield line

    await processor.process_stream(lines(), _NoopWorkspace())
    return recorder.rows


@pytest.mark.asyncio
async def test_a_file_change_codex_never_opened_reports_no_duration(api: ApiGet) -> None:
    """`codex_brace_echo_clean.jsonl`: the change arrives already finished.

    Codex sends no `item.started` for that `file_change` - its
    `item.completed` is the first and only thing it says about the change. The
    processor used to answer that single event with two rows, a start and a
    completion written back-to-back, and the duration rule then measured the
    distance between them. Here that would report 1500ms of editing, from a
    stream that never said when the edit began.

    One row is written now, so there is no pair and no duration - the same
    answer a truncated stream's orphan completion already gets.
    """
    rows = await _rows_codex_wrote("codex_brace_echo_clean.jsonl")

    response = await api(f"/observability/sessions/{SESSION_ID}/tools", rows)

    edits = [
        entry
        for entry in response.json()["executions"]
        if entry["tool_name"] == CODEX_TOOL_NAME_FILE_CHANGE
    ]
    assert [entry["operation_type"] for entry in edits] == [TOOL_EXECUTION_COMPLETED]
    assert edits[0]["duration_ms"] is None


@pytest.mark.asyncio
async def test_the_file_change_a_codex_did_open_is_timed_from_its_own_rows(
    api: ApiGet,
) -> None:
    """`codex_exec_recording.jsonl`: the other capture shape, which does open one.

    Its `item.started` for a `file_change` carries the change list, so both
    ends of the change are things codex said, 1.5s apart in this stamping, and
    the pair is timed like any other call. Dropping that start to be rid of
    the synthetic one would have thrown away a real measurement, and this is
    what refuses that fix.
    """
    rows = await _rows_codex_wrote("codex_exec_recording.jsonl")

    response = await api(f"/events/sessions/{SESSION_ID}/tools", rows)

    (edit,) = [tool for tool in response.json() if tool["tool_name"] == CODEX_TOOL_NAME_FILE_CHANGE]
    assert edit["call_count"] == 2  # item_1 (one.txt), item_3 (two.txt)
    assert edit["total_duration_ms"] == 3000
