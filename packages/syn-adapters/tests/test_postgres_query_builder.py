"""Tests for PostgreSQL query builder — boolean serialization and WHERE clause generation.

Regression tests for a bug where Python's str(False) produced 'False' but
PostgreSQL JSONB ->> extracts booleans as 'false' (lowercase JSON literal),
causing WHERE clauses to match zero rows.
"""

import pytest

from syn_adapters.projection_stores.postgres_query_builder import (
    _serialize_filter_value,
    build_query,
)


@pytest.mark.unit
class TestSerializeFilterValue:
    """Tests for _serialize_filter_value — JSONB text extraction compatibility."""

    def test_false_serializes_lowercase(self):
        assert _serialize_filter_value(False) == "false"

    def test_true_serializes_lowercase(self):
        assert _serialize_filter_value(True) == "true"

    def test_string_passthrough(self):
        assert _serialize_filter_value("hello") == "hello"

    def test_integer_passthrough(self):
        assert _serialize_filter_value(42) == "42"

    def test_none_passthrough(self):
        assert _serialize_filter_value(None) == "None"


@pytest.mark.unit
class TestBuildQuery:
    """Tests for build_query with boolean filters."""

    def test_boolean_false_filter(self):
        """REGRESSION: is_archived=False must produce 'false', not 'False'."""
        query, params = build_query("workflows", filters={"is_archived": False})
        assert "data->>'is_archived' = $1" in query
        assert params == ["false"]

    def test_boolean_true_filter(self):
        query, params = build_query("workflows", filters={"is_archived": True})
        assert params == ["true"]

    def test_mixed_filters(self):
        query, params = build_query(
            "workflows",
            filters={"is_archived": False, "workflow_type": "research"},
        )
        assert params == ["false", "research"]

    def test_no_filters(self):
        query, params = build_query("workflows")
        assert "WHERE" not in query
        assert params == []

    def test_order_by_default(self):
        query, _ = build_query("workflows")
        assert "ORDER BY updated_at DESC" in query

    def test_order_by_ascending(self):
        query, _ = build_query("workflows", order_by="name")
        assert "ORDER BY data->>'name' ASC" in query

    def test_order_by_descending(self):
        query, _ = build_query("workflows", order_by="-created_at")
        assert "ORDER BY data->>'created_at' DESC" in query

    def test_limit_and_offset(self):
        query, _ = build_query("workflows", limit=10, offset=20)
        assert "LIMIT 10" in query
        assert "OFFSET 20" in query
