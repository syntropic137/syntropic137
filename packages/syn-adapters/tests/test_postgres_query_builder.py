"""Tests for PostgreSQL query builder — boolean serialization and WHERE clause generation.

Regression tests for a bug where Python's str(False) produced 'False' but
PostgreSQL JSONB ->> extracts booleans as 'false' (lowercase JSON literal),
causing WHERE clauses to match zero rows.
"""

import pytest

from syn_adapters.projection_stores.postgres_query_builder import (
    _serialize_filter_value,
    build_count_query,
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
        _, params = build_query("workflows", filters={"is_archived": True})
        assert params == ["true"]

    def test_mixed_filters(self):
        _, params = build_query(
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


@pytest.mark.unit
class TestCollectionFilters:
    """A filter value may be several values, and several means ANY of them.

    Without this, a caller asking "which records match these twelve repos"
    has two moves: twelve round trips, or load the table and filter in Python
    — and the second is what every caller of repo_correlation did (#1253).
    """

    def test_list_becomes_any(self):
        query, params = build_query(
            "repo_correlation", filters={"repo_full_name": ["acme/api", "acme/web"]}
        )
        assert "data->>'repo_full_name' = ANY($1)" in query
        assert params == [["acme/api", "acme/web"]]

    def test_set_becomes_any(self):
        query, params = build_query("repo_correlation", filters={"repo_full_name": {"acme/api"}})
        assert "data->>'repo_full_name' = ANY($1)" in query
        assert params == [["acme/api"]]

    def test_members_are_serialized_like_scalars(self):
        """Each member goes through JSONB text extraction, booleans included."""
        _, params = build_query("workflows", filters={"is_archived": [False, True]})
        assert params == [["false", "true"]]

    def test_mixed_with_scalar_keeps_placeholder_order(self):
        query, params = build_query(
            "repo_correlation",
            filters={"repo_full_name": ["acme/api"], "kind": "execution"},
        )
        assert "data->>'repo_full_name' = ANY($1)" in query
        assert "data->>'kind' = $2" in query
        assert params == [["acme/api"], "execution"]

    def test_count_query_filters_the_same_way(self):
        """The count must not drift from the query it counts."""
        query, params = build_count_query(
            "repo_correlation", filters={"repo_full_name": ["acme/api", "acme/web"]}
        )
        assert "data->>'repo_full_name' = ANY($1)" in query
        assert params == [["acme/api", "acme/web"]]
