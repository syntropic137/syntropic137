"""Tests for schema validation in AgentEventStore.

Tests both positive (schema matches) and negative (schema mismatch) cases.

Updated to match simplified schema (ADR-029):
- No 'id' column (TimescaleDB manages internally)
- All string fields use 'text' type
"""

from unittest.mock import AsyncMock

import pytest

from syn_adapters.events.models import EXPECTED_COLUMNS
from syn_adapters.events.store import AgentEventStore, SchemaValidationError


@pytest.mark.integration
class TestSchemaValidation:
    """Tests for _validate_schema method."""

    @pytest.fixture
    def store(self) -> AgentEventStore:
        """Create a store instance."""
        return AgentEventStore("postgresql://test:test@localhost/test")

    @pytest.fixture
    def mock_conn(self) -> AsyncMock:
        """Create a mock connection."""
        return AsyncMock()

    # ==================== POSITIVE TESTS ====================

    async def test_valid_schema_passes(self, store: AgentEventStore, mock_conn: AsyncMock) -> None:
        """Should pass when schema matches expected columns."""
        # Mock DB returns matching schema (simplified - all text types)
        mock_conn.fetch.return_value = [
            {"column_name": "time", "data_type": "timestamp with time zone"},
            {"column_name": "event_type", "data_type": "text"},
            {"column_name": "session_id", "data_type": "text"},
            {"column_name": "execution_id", "data_type": "text"},
            {"column_name": "phase_id", "data_type": "text"},
            {"column_name": "data", "data_type": "jsonb"},
        ]

        # Should not raise
        await store._validate_schema(mock_conn)

    async def test_valid_schema_with_extra_columns(
        self, store: AgentEventStore, mock_conn: AsyncMock
    ) -> None:
        """Should pass when DB has extra columns beyond expected."""
        mock_conn.fetch.return_value = [
            {"column_name": "time", "data_type": "timestamp with time zone"},
            {"column_name": "event_type", "data_type": "text"},
            {"column_name": "session_id", "data_type": "text"},
            {"column_name": "execution_id", "data_type": "text"},
            {"column_name": "phase_id", "data_type": "text"},
            {"column_name": "data", "data_type": "jsonb"},
            {"column_name": "extra_column", "data_type": "text"},  # Extra column is OK
        ]

        # Should not raise - extra columns are allowed
        await store._validate_schema(mock_conn)

    # ==================== NEGATIVE TESTS ====================

    async def test_missing_column_raises(
        self, store: AgentEventStore, mock_conn: AsyncMock
    ) -> None:
        """Should raise SchemaValidationError when a column is missing."""
        # Missing 'session_id' column
        mock_conn.fetch.return_value = [
            {"column_name": "time", "data_type": "timestamp with time zone"},
            {"column_name": "event_type", "data_type": "text"},
            # session_id MISSING
            {"column_name": "execution_id", "data_type": "text"},
            {"column_name": "phase_id", "data_type": "text"},
            {"column_name": "data", "data_type": "jsonb"},
        ]

        with pytest.raises(SchemaValidationError) as exc_info:
            await store._validate_schema(mock_conn)

        assert "Missing column: session_id" in str(exc_info.value)

    async def test_wrong_type_raises(self, store: AgentEventStore, mock_conn: AsyncMock) -> None:
        """Should raise SchemaValidationError when column type is wrong."""
        # session_id should be text, not uuid
        mock_conn.fetch.return_value = [
            {"column_name": "time", "data_type": "timestamp with time zone"},
            {"column_name": "event_type", "data_type": "text"},
            {"column_name": "session_id", "data_type": "uuid"},  # WRONG TYPE
            {"column_name": "execution_id", "data_type": "text"},
            {"column_name": "phase_id", "data_type": "text"},
            {"column_name": "data", "data_type": "jsonb"},
        ]

        with pytest.raises(SchemaValidationError) as exc_info:
            await store._validate_schema(mock_conn)

        assert "session_id" in str(exc_info.value)
        assert "expected 'text'" in str(exc_info.value)
        assert "got 'uuid'" in str(exc_info.value)

    async def test_multiple_errors_reported(
        self, store: AgentEventStore, mock_conn: AsyncMock
    ) -> None:
        """Should report all mismatches, not just the first one."""
        # Multiple issues: missing column AND wrong type
        mock_conn.fetch.return_value = [
            {"column_name": "time", "data_type": "timestamp with time zone"},
            {"column_name": "event_type", "data_type": "varchar"},  # WRONG - should be text
            # session_id MISSING
            {"column_name": "execution_id", "data_type": "text"},
            {"column_name": "phase_id", "data_type": "text"},
            {"column_name": "data", "data_type": "jsonb"},
        ]

        with pytest.raises(SchemaValidationError) as exc_info:
            await store._validate_schema(mock_conn)

        error_msg = str(exc_info.value)
        assert "Missing column: session_id" in error_msg
        assert "event_type" in error_msg

    async def test_empty_table_raises(self, store: AgentEventStore, mock_conn: AsyncMock) -> None:
        """Should raise SchemaValidationError when table has no columns (doesn't exist)."""
        mock_conn.fetch.return_value = []

        with pytest.raises(SchemaValidationError) as exc_info:
            await store._validate_schema(mock_conn)

        # Should report all expected columns as missing
        error_msg = str(exc_info.value)
        for col in EXPECTED_COLUMNS:
            assert f"Missing column: {col}" in error_msg

    async def test_timestamp_without_tz_passes(
        self, store: AgentEventStore, mock_conn: AsyncMock
    ) -> None:
        """Timestamp without tz passes because validation uses first-word match.

        Note: This is permissive by design - both are 'timestamp' types.
        For stricter validation, update the comparison logic.
        """
        mock_conn.fetch.return_value = [
            {"column_name": "time", "data_type": "timestamp without time zone"},
            {"column_name": "event_type", "data_type": "text"},
            {"column_name": "session_id", "data_type": "text"},
            {"column_name": "execution_id", "data_type": "text"},
            {"column_name": "phase_id", "data_type": "text"},
            {"column_name": "data", "data_type": "jsonb"},
        ]

        # Passes because 'timestamp without time zone' starts with 'timestamp'
        await store._validate_schema(mock_conn)

    async def test_completely_wrong_time_type_raises(
        self, store: AgentEventStore, mock_conn: AsyncMock
    ) -> None:
        """Should catch when time column is completely wrong type."""
        mock_conn.fetch.return_value = [
            {"column_name": "time", "data_type": "bigint"},  # Completely wrong
            {"column_name": "event_type", "data_type": "text"},
            {"column_name": "session_id", "data_type": "text"},
            {"column_name": "execution_id", "data_type": "text"},
            {"column_name": "phase_id", "data_type": "text"},
            {"column_name": "data", "data_type": "jsonb"},
        ]

        with pytest.raises(SchemaValidationError) as exc_info:
            await store._validate_schema(mock_conn)

        assert "time" in str(exc_info.value)

    async def test_json_vs_jsonb_mismatch_raises(
        self, store: AgentEventStore, mock_conn: AsyncMock
    ) -> None:
        """Should catch json vs jsonb mismatch."""
        mock_conn.fetch.return_value = [
            {"column_name": "time", "data_type": "timestamp with time zone"},
            {"column_name": "event_type", "data_type": "text"},
            {"column_name": "session_id", "data_type": "text"},
            {"column_name": "execution_id", "data_type": "text"},
            {"column_name": "phase_id", "data_type": "text"},
            {"column_name": "data", "data_type": "json"},  # WRONG - should be jsonb
        ]

        with pytest.raises(SchemaValidationError) as exc_info:
            await store._validate_schema(mock_conn)

        assert "data" in str(exc_info.value)
        assert "jsonb" in str(exc_info.value)


class TestExpectedColumnsConstant:
    """Tests for EXPECTED_COLUMNS constant."""

    def test_expected_columns_has_all_required(self) -> None:
        """Verify EXPECTED_COLUMNS has all required columns (simplified schema)."""
        # No 'id' column in simplified schema
        required = {"time", "event_type", "session_id", "execution_id", "phase_id", "data"}
        assert set(EXPECTED_COLUMNS.keys()) == required

    def test_expected_columns_types(self) -> None:
        """Verify expected column types are correct (simplified - all text)."""
        assert EXPECTED_COLUMNS["session_id"] == "text"
        assert EXPECTED_COLUMNS["execution_id"] == "text"
        assert EXPECTED_COLUMNS["phase_id"] == "text"
        assert EXPECTED_COLUMNS["event_type"] == "text"
        assert EXPECTED_COLUMNS["time"] == "timestamp with time zone"
        assert EXPECTED_COLUMNS["data"] == "jsonb"
