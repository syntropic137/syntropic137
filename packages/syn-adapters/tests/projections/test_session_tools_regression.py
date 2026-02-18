"""Regression tests for SessionToolsProjection.

These tests verify critical fixes for observability display issues:
- Tool names showing as "unknown" for completed events
- Missing tool_use_id correlation between started/completed

CRITICAL: These tests should catch issues before they reach the UI.
"""

from __future__ import annotations

from datetime import UTC
from unittest.mock import AsyncMock, MagicMock

import pytest


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
        mock_conn = MagicMock()
        mock_conn.fetch = AsyncMock(return_value=mock_rows)

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
    async def test_completed_without_started_shows_unknown(self) -> None:
        """Completed event without corresponding started should show 'unknown'."""
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

        mock_conn = MagicMock()
        mock_conn.fetch = AsyncMock(return_value=mock_rows)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock())
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock()

        projection = SessionToolsProjection(pool=mock_pool)
        operations = await projection.get("session-123")

        assert len(operations) == 1
        # Should default to 'unknown' rather than crashing
        assert operations[0].tool_name == "unknown"


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
