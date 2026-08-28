"""Tests for projection store implementations.

These tests verify both InMemoryProjectionStore and PostgresProjectionStore
follow the ProjectionStoreProtocol correctly.
"""

import os
from datetime import UTC, datetime

import pytest

# Set test environment before imports
os.environ["APP_ENVIRONMENT"] = "test"

from syn_adapters.projection_stores import (
    InMemoryProjectionStore,
    ProjectionStoreProtocol,
    get_projection_store,
    reset_projection_store,
)


@pytest.fixture(autouse=True)
def reset_store():
    """Reset the projection store before each test."""
    reset_projection_store()
    yield
    reset_projection_store()


@pytest.fixture
def memory_store() -> InMemoryProjectionStore:
    """Create a fresh in-memory store for testing."""
    return InMemoryProjectionStore()


@pytest.mark.unit
class TestInMemoryProjectionStore:
    """Tests for InMemoryProjectionStore."""

    @pytest.mark.asyncio
    async def test_save_and_get(self, memory_store: InMemoryProjectionStore):
        """Test saving and retrieving a record."""
        data = {"name": "Test Workflow", "status": "pending"}
        await memory_store.save("workflows", "wf-1", data)

        result = await memory_store.get("workflows", "wf-1")
        assert result == data

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, memory_store: InMemoryProjectionStore):
        """Test getting a non-existent record returns None."""
        result = await memory_store.get("workflows", "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_all(self, memory_store: InMemoryProjectionStore):
        """Test getting all records for a projection."""
        await memory_store.save("workflows", "wf-1", {"name": "Workflow 1"})
        await memory_store.save("workflows", "wf-2", {"name": "Workflow 2"})
        await memory_store.save("workflows", "wf-3", {"name": "Workflow 3"})

        results = await memory_store.get_all("workflows")
        assert len(results) == 3
        names = {r["name"] for r in results}
        assert names == {"Workflow 1", "Workflow 2", "Workflow 3"}

    @pytest.mark.asyncio
    async def test_get_all_empty(self, memory_store: InMemoryProjectionStore):
        """Test getting all records from empty projection."""
        results = await memory_store.get_all("workflows")
        assert results == []

    @pytest.mark.asyncio
    async def test_delete(self, memory_store: InMemoryProjectionStore):
        """Test deleting a record."""
        await memory_store.save("workflows", "wf-1", {"name": "Test"})
        await memory_store.delete("workflows", "wf-1")

        result = await memory_store.get("workflows", "wf-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_existing(self, memory_store: InMemoryProjectionStore):
        """Test updating an existing record."""
        await memory_store.save("workflows", "wf-1", {"name": "Original", "status": "pending"})
        await memory_store.save("workflows", "wf-1", {"name": "Updated", "status": "active"})

        result = await memory_store.get("workflows", "wf-1")
        assert result["name"] == "Updated"
        assert result["status"] == "active"

    @pytest.mark.asyncio
    async def test_query_with_filters(self, memory_store: InMemoryProjectionStore):
        """Test querying with filters."""
        await memory_store.save("workflows", "wf-1", {"name": "A", "status": "pending"})
        await memory_store.save("workflows", "wf-2", {"name": "B", "status": "active"})
        await memory_store.save("workflows", "wf-3", {"name": "C", "status": "pending"})

        results = await memory_store.query("workflows", filters={"status": "pending"})
        assert len(results) == 2
        statuses = {r["status"] for r in results}
        assert statuses == {"pending"}

    @pytest.mark.asyncio
    async def test_query_with_boolean_filter(self, memory_store: InMemoryProjectionStore):
        """REGRESSION: boolean filters must work correctly.

        Python str(False)='False' vs JSONB 'false' caused zero matches
        in Postgres. InMemoryProjectionStore must also handle booleans
        consistently so tests don't diverge from prod behavior.
        """
        await memory_store.save("workflows", "wf-1", {"name": "Active", "is_archived": False})
        await memory_store.save("workflows", "wf-2", {"name": "Archived", "is_archived": True})
        await memory_store.save("workflows", "wf-3", {"name": "Also Active", "is_archived": False})

        results = await memory_store.query("workflows", filters={"is_archived": False})
        assert len(results) == 2
        names = {r["name"] for r in results}
        assert names == {"Active", "Also Active"}

        results = await memory_store.query("workflows", filters={"is_archived": True})
        assert len(results) == 1
        assert results[0]["name"] == "Archived"

    @pytest.mark.asyncio
    async def test_query_with_order(self, memory_store: InMemoryProjectionStore):
        """Test querying with ordering."""
        await memory_store.save("workflows", "wf-1", {"name": "Zebra"})
        await memory_store.save("workflows", "wf-2", {"name": "Apple"})
        await memory_store.save("workflows", "wf-3", {"name": "Mango"})

        # Ascending
        results = await memory_store.query("workflows", order_by="name")
        assert results[0]["name"] == "Apple"

        # Descending
        results = await memory_store.query("workflows", order_by="-name")
        assert results[0]["name"] == "Zebra"

    @pytest.mark.asyncio
    async def test_query_with_pagination(self, memory_store: InMemoryProjectionStore):
        """Test querying with limit and offset."""
        for i in range(10):
            await memory_store.save("workflows", f"wf-{i}", {"index": i})

        results = await memory_store.query("workflows", limit=3, offset=2)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_position_tracking(self, memory_store: InMemoryProjectionStore):
        """Test getting and setting event position."""
        # Initially None
        position = await memory_store.get_position("workflows")
        assert position is None

        # Set position
        await memory_store.set_position("workflows", 42)
        position = await memory_store.get_position("workflows")
        assert position == 42

        # Update position
        await memory_store.set_position("workflows", 100)
        position = await memory_store.get_position("workflows")
        assert position == 100

    @pytest.mark.asyncio
    async def test_last_updated(self, memory_store: InMemoryProjectionStore):
        """Test getting last update timestamp."""
        before = datetime.now(UTC)
        await memory_store.save("workflows", "wf-1", {"name": "Test"})
        after = datetime.now(UTC)

        last_updated = await memory_store.get_last_updated("workflows")
        assert last_updated is not None
        assert before <= last_updated <= after

    @pytest.mark.asyncio
    async def test_clear(self, memory_store: InMemoryProjectionStore):
        """Test clearing all data."""
        await memory_store.save("workflows", "wf-1", {"name": "Test"})
        await memory_store.save("sessions", "s-1", {"name": "Session"})
        await memory_store.set_position("workflows", 42)

        memory_store.clear()

        assert await memory_store.get_all("workflows") == []
        assert await memory_store.get_all("sessions") == []
        assert await memory_store.get_position("workflows") is None

    @pytest.mark.asyncio
    async def test_clear_projection(self, memory_store: InMemoryProjectionStore):
        """Test clearing a specific projection."""
        await memory_store.save("workflows", "wf-1", {"name": "Test"})
        await memory_store.save("sessions", "s-1", {"name": "Session"})

        memory_store.clear_projection("workflows")

        assert await memory_store.get_all("workflows") == []
        assert len(await memory_store.get_all("sessions")) == 1

    @pytest.mark.asyncio
    async def test_projection_isolation(self, memory_store: InMemoryProjectionStore):
        """Test that projections are isolated from each other."""
        await memory_store.save("workflows", "id-1", {"type": "workflow"})
        await memory_store.save("sessions", "id-1", {"type": "session"})

        workflow = await memory_store.get("workflows", "id-1")
        session = await memory_store.get("sessions", "id-1")

        assert workflow["type"] == "workflow"
        assert session["type"] == "session"


class TestGetProjectionStore:
    """Tests for the get_projection_store factory function."""

    def test_returns_memory_store_in_test_env(self):
        """Test that in-memory store is returned in test environment."""
        store = get_projection_store()
        assert isinstance(store, InMemoryProjectionStore)

    def test_returns_protocol_compliant_store(self):
        """Test that the returned store implements the protocol."""
        store = get_projection_store()
        assert isinstance(store, ProjectionStoreProtocol)

    def test_singleton_pattern(self):
        """Test that the same instance is returned."""
        store1 = get_projection_store()
        store2 = get_projection_store()
        assert store1 is store2

    def test_reset_clears_cache(self):
        """Test that reset clears the cached instance."""
        store1 = get_projection_store()
        reset_projection_store()
        store2 = get_projection_store()
        assert store1 is not store2


class TestProjectionStoreProtocol:
    """Tests for protocol compliance."""

    def test_memory_store_is_protocol_compliant(self):
        """Test that InMemoryProjectionStore implements the protocol."""
        store = InMemoryProjectionStore()
        assert isinstance(store, ProjectionStoreProtocol)

    def test_protocol_has_required_methods(self):
        """Test that the protocol defines all required methods."""
        required_methods = [
            "save",
            "get",
            "get_all",
            "delete",
            "query",
            "get_position",
            "set_position",
            "get_last_updated",
        ]
        for method in required_methods:
            assert hasattr(ProjectionStoreProtocol, method)


class TestNullOrderingIsLast:
    """#920: rows that cannot answer the sort must not outrank rows that can.

    Postgres defaults ``ORDER BY ... DESC`` to ``NULLS FIRST``, and the
    in-memory store reproduced that by folding the is-None flag into a reversed
    sort key. Either way, every row MISSING the sort field ranked above every
    row that had it.

    Concretely: artifacts created before ArtifactCreated v4 carry a null
    ``created_at``. With ~100 of them in the store, a newly created artifact
    sorted by ``-created_at`` landed on the LAST page. To a user that is
    indistinguishable from the write having failed.

    The aggregate-level test for #920 asserts the timestamp is now stamped. It
    cannot catch this, because the defect lives in the store's ordering rather
    than in the event.
    """

    def test_memory_store_puts_missing_values_last_in_both_directions(self) -> None:
        from syn_adapters.projection_stores.memory_store_helpers import apply_sorting

        rows = [
            {"id": "legacy_a", "created_at": None},
            {"id": "newest", "created_at": "2026-08-28T00:00:00+00:00"},
            {"id": "legacy_b", "created_at": None},
            {"id": "older", "created_at": "2026-08-27T00:00:00+00:00"},
        ]

        desc = [r["id"] for r in apply_sorting(rows, "-created_at")]
        assert desc[:2] == ["newest", "older"], (
            "newest-first must place timestamped rows ahead of legacy nulls; "
            "a null that outranks a real value is #920"
        )
        assert set(desc[2:]) == {"legacy_a", "legacy_b"}

        asc = [r["id"] for r in apply_sorting(rows, "created_at")]
        assert asc[:2] == ["older", "newest"]
        assert set(asc[2:]) == {"legacy_a", "legacy_b"}, (
            "nulls go last in ASCENDING order too; direction and null "
            "placement must stay independent"
        )

    def test_postgres_order_clause_declares_nulls_last(self) -> None:
        """The two stores must agree, or a green test hides a production bug."""
        from syn_adapters.projection_stores.postgres_query_builder import _build_order_clause

        assert _build_order_clause("-created_at") == (
            " ORDER BY data->>'created_at' DESC NULLS LAST"
        )
        assert _build_order_clause("created_at") == (" ORDER BY data->>'created_at' ASC NULLS LAST")
