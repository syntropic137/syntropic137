"""Tests for InMemoryDedupAdapter."""

from __future__ import annotations

import pytest

from syn_adapters.dedup.memory_dedup import InMemoryDedupAdapter


class TestInMemoryDedup:
    @pytest.mark.asyncio
    async def test_first_key_is_not_duplicate(self) -> None:
        adapter = InMemoryDedupAdapter()
        assert await adapter.is_duplicate("key-1") is False

    @pytest.mark.asyncio
    async def test_second_key_is_duplicate(self) -> None:
        adapter = InMemoryDedupAdapter()
        await adapter.is_duplicate("key-1")
        assert await adapter.is_duplicate("key-1") is True

    @pytest.mark.asyncio
    async def test_different_keys_not_duplicates(self) -> None:
        adapter = InMemoryDedupAdapter()
        assert await adapter.is_duplicate("key-1") is False
        assert await adapter.is_duplicate("key-2") is False

    @pytest.mark.asyncio
    async def test_mark_seen_makes_key_duplicate(self) -> None:
        adapter = InMemoryDedupAdapter()
        await adapter.mark_seen("key-1")
        assert await adapter.is_duplicate("key-1") is True

    @pytest.mark.asyncio
    async def test_lru_eviction_at_max_size(self) -> None:
        adapter = InMemoryDedupAdapter(max_size=3)

        # Fill to capacity
        await adapter.is_duplicate("a")
        await adapter.is_duplicate("b")
        await adapter.is_duplicate("c")

        # Adding a 4th should evict "a" (oldest)
        await adapter.is_duplicate("d")

        # Verify internal state: "a" was evicted
        assert "a" not in adapter._seen
        # "b", "c", "d" should still be present
        assert "b" in adapter._seen
        assert "c" in adapter._seen
        assert "d" in adapter._seen

    @pytest.mark.asyncio
    async def test_lru_access_refreshes_entry(self) -> None:
        adapter = InMemoryDedupAdapter(max_size=3)

        await adapter.is_duplicate("a")
        await adapter.is_duplicate("b")
        await adapter.is_duplicate("c")

        # Access "a" again to refresh its position (moves to end)
        assert await adapter.is_duplicate("a") is True

        # Adding "d" should now evict "b" (oldest untouched), not "a"
        await adapter.is_duplicate("d")

        assert "a" in adapter._seen  # refreshed, still here
        assert "b" not in adapter._seen  # evicted
