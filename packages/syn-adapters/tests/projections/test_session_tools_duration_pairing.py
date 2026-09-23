"""Both of SessionToolsProjection's query paths must time a call the same way.

`get()` and `query()` are two independent reads over the same rows - the first
by session, the second filtered by execution or tool - and each builds its own
list. A duration resolved in one and not the other is the shape this projection
has been split into before: the readers disagree, and which number a dashboard
shows depends on which endpoint it happened to call.

The pairing itself (#1064) is proved against the API in
`apps/syn-api/tests/test_tool_duration_reaches_the_api.py`; what is pinned here
is that neither path can be fixed alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from syn_adapters.projections.session_tools import SessionToolsProjection
from syn_shared.events import TOOL_EXECUTION_COMPLETED, TOOL_EXECUTION_STARTED

if TYPE_CHECKING:
    from collections.abc import Sequence

pytestmark = pytest.mark.unit

STARTED_AT = datetime(2026, 3, 4, 12, 0, 0, tzinfo=UTC)
TOOK = timedelta(milliseconds=1500)

_PayloadValue = str | bool | int


@dataclass(frozen=True)
class _Payload:
    """An observation payload, holding only the keys its producer sets.

    `record_tool_completed` writes no duration, which is the whole of #1064.
    """

    tool_name: str
    tool_use_id: str
    input_preview: str | None = None
    success: bool | None = None
    output_preview: str | None = None

    def stored(self) -> dict[str, _PayloadValue]:
        """The payload as the store holds it: an unset key is absent, not null."""
        written: dict[str, _PayloadValue] = {}
        for name, value in vars(self).items():
            if value is not None:
                written[name] = value
        return written


@dataclass(frozen=True)
class _Row:
    """A row shaped like the `asyncpg.Record` both query paths read."""

    event_type: str
    time: datetime
    payload: _Payload

    def __getitem__(self, column: str) -> str | datetime | dict[str, _PayloadValue]:
        if column == "data":
            return self.payload.stored()
        if column == "event_type":
            return self.event_type
        return self.time


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
    def __init__(self, rows: Sequence[_Row]) -> None:
        self._rows = rows

    def acquire(self) -> _Acquire:
        return _Acquire(self._rows)


def _rows() -> list[_Row]:
    """One Bash call, 1.5s, in the shape `record_tool_completed` stores."""
    return [
        _Row(
            TOOL_EXECUTION_STARTED,
            STARTED_AT,
            _Payload(tool_name="Bash", tool_use_id="toolu_1", input_preview="ls"),
        ),
        _Row(
            TOOL_EXECUTION_COMPLETED,
            STARTED_AT + TOOK,
            _Payload(tool_name="Bash", tool_use_id="toolu_1", success=True, output_preview="ok"),
        ),
    ]


@pytest.mark.asyncio
async def test_both_query_paths_report_the_same_duration() -> None:
    projection = SessionToolsProjection(pool=_Pool(_rows()))  # type: ignore[arg-type]  # asyncpg stand-in

    by_session = await projection.get("sess-1064")
    by_filter = await projection.query(execution_id="exec-1", tool_name="Bash")

    assert [op.duration_ms for op in by_session] == [None, 1500]
    assert [op.duration_ms for op in by_filter] == [None, 1500]
