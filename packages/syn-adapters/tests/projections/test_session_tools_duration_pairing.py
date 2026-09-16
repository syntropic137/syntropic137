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

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from syn_adapters.projections.session_tools import SessionToolsProjection
from syn_shared.events import TOOL_EXECUTION_COMPLETED, TOOL_EXECUTION_STARTED

if TYPE_CHECKING:
    from collections.abc import Sequence

pytestmark = pytest.mark.unit

STARTED_AT = datetime(2026, 3, 4, 12, 0, 0, tzinfo=UTC)
TOOK = timedelta(milliseconds=1500)


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
    def __init__(self, rows: Sequence[dict[str, Any]]) -> None:
        self._rows = rows

    def acquire(self) -> _Acquire:
        return _Acquire(self._rows)


def _rows() -> list[dict[str, Any]]:
    """One Bash call, 1.5s, in the shape `record_tool_completed` stores."""
    return [
        {
            "event_type": TOOL_EXECUTION_STARTED,
            "time": STARTED_AT,
            "data": {"tool_name": "Bash", "tool_use_id": "toolu_1", "input_preview": "ls"},
        },
        {
            "event_type": TOOL_EXECUTION_COMPLETED,
            "time": STARTED_AT + TOOK,
            "data": {
                "tool_name": "Bash",
                "tool_use_id": "toolu_1",
                "success": True,
                "output_preview": "ok",
            },
        },
    ]


@pytest.mark.asyncio
async def test_both_query_paths_report_the_same_duration() -> None:
    projection = SessionToolsProjection(pool=_Pool(_rows()))  # type: ignore[arg-type]  # asyncpg stand-in

    by_session = await projection.get("sess-1064")
    by_filter = await projection.query(execution_id="exec-1", tool_name="Bash")

    assert [op.duration_ms for op in by_session] == [None, 1500]
    assert [op.duration_ms for op in by_filter] == [None, 1500]
