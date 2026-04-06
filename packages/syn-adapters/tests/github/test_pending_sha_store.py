"""Unit tests for InMemoryPendingSHAStore (#602)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from syn_adapters.github.pending_sha_store import InMemoryPendingSHAStore
from syn_domain.contexts.github.slices.event_pipeline.pending_sha_port import PendingSHA


def _make_pending(
    repository: str = "owner/repo",
    sha: str = "abc123",
    pr_number: int = 42,
    branch: str = "feature",
    installation_id: str = "inst-1",
    registered_at: datetime | None = None,
) -> PendingSHA:
    return PendingSHA(
        repository=repository,
        sha=sha,
        pr_number=pr_number,
        branch=branch,
        installation_id=installation_id,
        registered_at=registered_at or datetime.now(UTC),
    )


@pytest.mark.unit
class TestRegister:
    @pytest.mark.asyncio
    async def test_register_stores_sha(self) -> None:
        store = InMemoryPendingSHAStore()
        pending = _make_pending()
        await store.register(pending)

        result = await store.list_pending()
        assert len(result) == 1
        assert result[0] is pending

    @pytest.mark.asyncio
    async def test_register_duplicate_is_noop(self) -> None:
        store = InMemoryPendingSHAStore()
        first = _make_pending(sha="abc123")
        second = _make_pending(sha="abc123", branch="other-branch")

        await store.register(first)
        await store.register(second)

        result = await store.list_pending()
        assert len(result) == 1
        assert result[0] is first  # First registration wins

    @pytest.mark.asyncio
    async def test_register_different_shas(self) -> None:
        store = InMemoryPendingSHAStore()
        await store.register(_make_pending(sha="aaa"))
        await store.register(_make_pending(sha="bbb"))

        result = await store.list_pending()
        assert len(result) == 2


@pytest.mark.unit
class TestRemove:
    @pytest.mark.asyncio
    async def test_remove_existing(self) -> None:
        store = InMemoryPendingSHAStore()
        await store.register(_make_pending(sha="abc123"))
        await store.remove("owner/repo", "abc123")

        result = await store.list_pending()
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_remove_nonexistent_is_noop(self) -> None:
        store = InMemoryPendingSHAStore()
        await store.remove("owner/repo", "nonexistent")
        # No error raised


@pytest.mark.unit
class TestCleanupStale:
    @pytest.mark.asyncio
    async def test_removes_old_entries(self) -> None:
        store = InMemoryPendingSHAStore()
        old = _make_pending(sha="old", registered_at=datetime.now(UTC) - timedelta(hours=3))
        fresh = _make_pending(sha="fresh", registered_at=datetime.now(UTC))

        await store.register(old)
        await store.register(fresh)

        removed = await store.cleanup_stale(max_age=timedelta(hours=2))
        assert removed == 1

        result = await store.list_pending()
        assert len(result) == 1
        assert result[0].sha == "fresh"

    @pytest.mark.asyncio
    async def test_returns_zero_when_nothing_stale(self) -> None:
        store = InMemoryPendingSHAStore()
        await store.register(_make_pending())

        removed = await store.cleanup_stale(max_age=timedelta(hours=2))
        assert removed == 0


@pytest.mark.unit
class TestListPending:
    @pytest.mark.asyncio
    async def test_empty_store(self) -> None:
        store = InMemoryPendingSHAStore()
        result = await store.list_pending()
        assert result == []
