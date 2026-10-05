"""Regression tests for SessionToolsProjection.

These tests verify critical fixes for observability display issues:
- Tool names showing as "unknown" for completed events
- Missing tool_use_id correlation between started/completed

CRITICAL: These tests should catch issues before they reach the UI.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


#: One column of a fixture row: the event type, its time, or its JSON payload.
type _Cell = str | datetime | Mapping[str, str | bool | int]


def _connection_serving(rows: Sequence[Mapping[str, _Cell]]) -> MagicMock:
    """A connection that answers the session-tools read with ``rows``.

    Also answers what that read now issues around it (E2): the plan setting
    ``agent_event_span.custom_plans`` runs, and the span lookup on the day
    rollup, answered with the UTC days the rows fall on. The bounded read
    itself returns the rows unfiltered; they all lie inside that span.
    """
    times = [row["time"] for row in rows if isinstance(row["time"], datetime)]
    days = [t.astimezone(UTC).date() for t in times]

    async def fetch(
        query: str, *_args: object
    ) -> Sequence[Mapping[str, _Cell]] | list[dict[str, date | None]]:
        if "agent_event_day_rollup" in query:
            span: dict[str, date | None] = {
                "first_day": min(days, default=None),
                "last_day": max(days, default=None),
            }
            return [span]
        return rows

    conn = MagicMock()
    conn.fetch = AsyncMock(side_effect=fetch)
    conn.execute = AsyncMock(return_value="SET")
    return conn


@pytest.mark.unit
class TestToolNameEnrichment:
    """Tests for tool_name enrichment via JOIN on tool_use_id.

    REGRESSION: tool_execution_completed events don't have tool_name
    because Claude's PostToolUse hook doesn't receive it.
    The projection must JOIN with tool_execution_started to get it.
    """

    @pytest.mark.asyncio
    async def test_completed_event_gets_tool_name_from_started(self) -> None:
        """REGRESSION: tool_execution_completed should get tool_name from started."""
        from datetime import datetime

        from syn_adapters.projections.session_tools import SessionToolsProjection

        # Mock database rows: started has tool_name, completed doesn't
        mock_rows = [
            {
                "event_type": "tool_execution_started",
                "time": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
                "data": {
                    "tool_name": "Bash",
                    "tool_use_id": "toolu_123",
                    "input_preview": '{"command": "ls"}',
                },
            },
            {
                "event_type": "tool_execution_completed",
                "time": datetime(2024, 1, 1, 12, 0, 1, tzinfo=UTC),
                "data": {
                    # After JOIN, this should have tool_name from started
                    "tool_name": "Bash",  # Simulating the JOIN result
                    "tool_use_id": "toolu_123",
                    "success": True,
                    "duration_ms": 500,
                },
            },
        ]

        # Create mock pool and connection
        mock_conn = _connection_serving(mock_rows)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock())
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock()

        # Test
        projection = SessionToolsProjection(pool=mock_pool)
        operations = await projection.get("session-123")

        # Assertions
        assert len(operations) == 2

        # Started event has tool_name
        started = operations[0]
        assert started.tool_name == "Bash"
        assert started.tool_use_id == "toolu_123"
        assert started.is_started

        # Completed event should ALSO have tool_name (from JOIN)
        completed = operations[1]
        assert completed.tool_name == "Bash", (
            "REGRESSION: tool_execution_completed should get tool_name from started"
        )
        assert completed.tool_use_id == "toolu_123"
        assert completed.is_completed
        assert completed.success is True

    @pytest.mark.asyncio
    async def test_completed_without_started_shows_empty_string(self) -> None:
        """Completed event without corresponding started should have empty tool_name.

        Empty string is intentional: the UI treats falsy tool_name as "no tool"
        and suppresses the wrench detail row, which is correct for orphaned events.
        The SQL layer uses COALESCE(..., 'unknown') but that only applies to real
        DB rows; mock rows without tool_name should yield "" not "unknown".
        """
        from datetime import datetime

        from syn_adapters.projections.session_tools import SessionToolsProjection

        # Only completed event, no started (edge case)
        mock_rows = [
            {
                "event_type": "tool_execution_completed",
                "time": datetime(2024, 1, 1, 12, 0, 1, tzinfo=UTC),
                "data": {
                    # No tool_name, JOIN couldn't find match
                    "tool_use_id": "toolu_orphan",
                    "success": True,
                },
            },
        ]

        mock_conn = _connection_serving(mock_rows)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock())
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock()

        projection = SessionToolsProjection(pool=mock_pool)
        operations = await projection.get("session-123")

        assert len(operations) == 1
        # Should default to "" (empty, suppresses UI wrench row) rather than crashing
        assert operations[0].tool_name == ""


@pytest.mark.unit
class TestRowToOperation:
    """Tests for _row_to_operation method."""

    def test_started_event_extracts_all_fields(self) -> None:
        """Started events should extract tool_name, tool_use_id, input_preview."""
        from datetime import datetime

        from syn_adapters.projections.session_tools import SessionToolsProjection

        projection = SessionToolsProjection()
        row = {
            "event_type": "tool_execution_started",
            "time": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            "data": {
                "tool_name": "Read",
                "tool_use_id": "toolu_abc",
                "input_preview": '{"path": "/file.txt"}',
            },
        }

        op = projection._row_to_operation(row)

        assert op.tool_name == "Read"
        assert op.tool_use_id == "toolu_abc"
        assert op.input_preview == '{"path": "/file.txt"}'
        assert op.operation_type == "tool_execution_started"
        assert op.is_started
        assert not op.is_completed

    def test_completed_event_extracts_all_fields(self) -> None:
        """Completed events should extract success, duration_ms, output_preview."""
        from datetime import datetime

        from syn_adapters.projections.session_tools import SessionToolsProjection

        projection = SessionToolsProjection()
        row = {
            "event_type": "tool_execution_completed",
            "time": datetime(2024, 1, 1, 12, 0, 1, tzinfo=UTC),
            "data": {
                "tool_name": "Write",
                "tool_use_id": "toolu_def",
                "success": True,
                "duration_ms": 150,
                "output_preview": "File written successfully",
            },
        }

        op = projection._row_to_operation(row)

        assert op.tool_name == "Write"
        assert op.tool_use_id == "toolu_def"
        assert op.success is True
        assert op.duration_ms == 150
        assert op.output_preview == "File written successfully"
        assert op.operation_type == "tool_execution_completed"
        assert op.is_completed
        assert not op.is_started

    def test_json_string_data_is_parsed(self) -> None:
        """Data field as JSON string should be parsed correctly."""
        import json
        from datetime import datetime

        from syn_adapters.projections.session_tools import SessionToolsProjection

        projection = SessionToolsProjection()
        row = {
            "event_type": "tool_execution_started",
            "time": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            "data": json.dumps(
                {
                    "tool_name": "Bash",
                    "tool_use_id": "toolu_string",
                }
            ),
        }

        op = projection._row_to_operation(row)

        assert op.tool_name == "Bash"
        assert op.tool_use_id == "toolu_string"
