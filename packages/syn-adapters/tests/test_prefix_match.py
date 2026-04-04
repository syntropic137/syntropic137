"""Tests for partial-ID prefix matching (issue #508).

Verifies that resolve_by_prefix correctly resolves full IDs, partial prefixes,
handles ambiguous matches, and returns not-found for no matches.
"""

import os

import pytest

# Set test environment before imports
os.environ["APP_ENVIRONMENT"] = "test"

from syn_adapters.projection_stores import InMemoryProjectionStore, reset_projection_store
from syn_adapters.projection_stores.prefix_match import (
    PrefixMatchResult,
    format_ambiguous_error,
    resolve_by_prefix,
)


@pytest.fixture(autouse=True)
def reset_store() -> None:
    """Reset the projection store before each test."""
    reset_projection_store()
    yield  # type: ignore[misc]
    reset_projection_store()


@pytest.fixture
def store() -> InMemoryProjectionStore:
    return InMemoryProjectionStore()


NAMESPACE = "test_projection"


@pytest.mark.asyncio
async def test_exact_match(store: InMemoryProjectionStore) -> None:
    """Full UUID resolves immediately via exact match."""
    full_id = "abc12345-6789-0000-1111-222233334444"
    await store.save(NAMESPACE, full_id, {"name": "test"})

    result = await resolve_by_prefix(store, NAMESPACE, full_id)

    assert result.is_exact
    assert result.full_id == full_id
    assert not result.is_ambiguous
    assert not result.is_not_found


@pytest.mark.asyncio
async def test_prefix_unique_match(store: InMemoryProjectionStore) -> None:
    """A unique prefix resolves to the full ID."""
    full_id = "abc12345-6789-0000-1111-222233334444"
    other_id = "def67890-1234-0000-1111-222233334444"
    await store.save(NAMESPACE, full_id, {"name": "first"})
    await store.save(NAMESPACE, other_id, {"name": "second"})

    result = await resolve_by_prefix(store, NAMESPACE, "abc12")

    assert result.is_exact
    assert result.full_id == full_id


@pytest.mark.asyncio
async def test_prefix_ambiguous_match(store: InMemoryProjectionStore) -> None:
    """Multiple matches returns ambiguous result with candidates."""
    id1 = "abc12345-aaaa-0000-0000-000000000001"
    id2 = "abc12345-bbbb-0000-0000-000000000002"
    await store.save(NAMESPACE, id1, {"name": "first"})
    await store.save(NAMESPACE, id2, {"name": "second"})

    result = await resolve_by_prefix(store, NAMESPACE, "abc12")

    assert result.is_ambiguous
    assert result.full_id is None
    assert len(result.candidates) == 2
    assert id1 in result.candidates
    assert id2 in result.candidates


@pytest.mark.asyncio
async def test_prefix_no_match(store: InMemoryProjectionStore) -> None:
    """No matches returns not-found result."""
    await store.save(NAMESPACE, "abc12345", {"name": "test"})

    result = await resolve_by_prefix(store, NAMESPACE, "zzz")

    assert result.is_not_found
    assert result.full_id is None
    assert len(result.candidates) == 0


@pytest.mark.asyncio
async def test_empty_projection(store: InMemoryProjectionStore) -> None:
    """Empty projection returns not-found."""
    result = await resolve_by_prefix(store, NAMESPACE, "abc")

    assert result.is_not_found


@pytest.mark.asyncio
async def test_get_by_prefix_memory_store(store: InMemoryProjectionStore) -> None:
    """InMemoryProjectionStore.get_by_prefix returns correct matches."""
    await store.save(NAMESPACE, "aaa-111", {"v": 1})
    await store.save(NAMESPACE, "aaa-222", {"v": 2})
    await store.save(NAMESPACE, "bbb-111", {"v": 3})

    matches = await store.get_by_prefix(NAMESPACE, "aaa")
    assert len(matches) == 2
    keys = {m[0] for m in matches}
    assert keys == {"aaa-111", "aaa-222"}


def test_format_ambiguous_error() -> None:
    """Ambiguous error message includes candidates and instructions."""
    msg = format_ambiguous_error("Workflow", "abc12", ["abc12345-aaaa", "abc12345-bbbb"])
    assert "abc12" in msg
    assert "workflow" in msg.lower()
    assert "abc12345-aa" in msg
    assert "disambiguate" in msg.lower()


def test_prefix_match_result_properties() -> None:
    """PrefixMatchResult properties work correctly."""
    exact = PrefixMatchResult(full_id="abc", candidates=["abc"])
    assert exact.is_exact
    assert not exact.is_ambiguous
    assert not exact.is_not_found

    ambiguous = PrefixMatchResult(full_id=None, candidates=["a1", "a2"])
    assert not ambiguous.is_exact
    assert ambiguous.is_ambiguous
    assert not ambiguous.is_not_found

    not_found = PrefixMatchResult(full_id=None, candidates=[])
    assert not not_found.is_exact
    assert not not_found.is_ambiguous
    assert not_found.is_not_found
