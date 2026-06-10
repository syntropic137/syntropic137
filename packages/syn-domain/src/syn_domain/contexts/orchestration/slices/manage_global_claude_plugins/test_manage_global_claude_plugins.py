# See ADR-066: tests use the lock projection directly to seed pre-registered
# plugins; AddGlobalClaudePluginHandler now requires lock-first registration
# (the API does no fetching).
"""Tests for the manage_global_claude_plugins slice (issue #726, Phase A redesign)."""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from datetime import UTC, datetime

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.storage.in_memory_claude_plugin_repositories import (
    InMemoryGlobalClaudePluginRegistryRepository,
)
from syn_domain.contexts.orchestration._shared.claude_plugin_errors import (
    ClaudePluginNotRegistered,
)
from syn_domain.contexts.orchestration.slices.manage_global_claude_plugins import (
    AddGlobalClaudePluginHandler,
    GlobalClaudePluginNotFoundError,
    GlobalClaudePluginsProjection,
    ListGlobalClaudePluginsHandler,
    RemoveGlobalClaudePluginHandler,
)
from syn_domain.contexts.orchestration.slices.register_claude_plugin.projection import (
    ClaudePluginLockProjection,
)


def _make_empty_lock() -> ClaudePluginLockProjection:
    """Build an empty lock projection backed by in-memory storage."""
    return ClaudePluginLockProjection(InMemoryProjectionStore())


async def _seed_lock(
    projection: ClaudePluginLockProjection,
    *,
    name: str,
    source_url: str,
    version: str,
    sha: str,
) -> None:
    await projection.on_claude_plugin_registered(
        {
            "source_url": source_url,
            "version": version,
            "name": name,
            "resolved_sha": sha,
            "tree_storage_prefix": f"prefix-{sha}",
            "registered_at": datetime.now(UTC).isoformat(),
        }
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_then_list_returns_entry() -> None:
    lock = _make_empty_lock()
    await _seed_lock(
        lock,
        name="foo",
        source_url="https://github.com/example/foo",
        version="1.0.0",
        sha="aaa",
    )

    repo = InMemoryGlobalClaudePluginRegistryRepository()
    add = AddGlobalClaudePluginHandler(repo=repo, lock_projection=lock)

    result = await add.handle(name="foo", version="1.0.0")

    assert result.name == "foo"
    aggregate = await repo.get_by_id("global-claude-plugins")
    assert aggregate is not None
    assert aggregate.has("foo")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_unregistered_plugin_raises_typed_error() -> None:
    lock = _make_empty_lock()
    repo = InMemoryGlobalClaudePluginRegistryRepository()
    add = AddGlobalClaudePluginHandler(repo=repo, lock_projection=lock)

    with pytest.raises(ClaudePluginNotRegistered):
        await add.handle(name="missing", version="1.0.0")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_is_idempotent_on_duplicate_name() -> None:
    lock = _make_empty_lock()
    await _seed_lock(
        lock,
        name="foo",
        source_url="https://github.com/example/foo",
        version="1.0.0",
        sha="aaa",
    )

    repo = InMemoryGlobalClaudePluginRegistryRepository()
    add = AddGlobalClaudePluginHandler(repo=repo, lock_projection=lock)

    first = await add.handle(name="foo", version="1.0.0")
    second = await add.handle(name="foo", version="1.0.0")

    assert first == second
    aggregate = await repo.get_by_id("global-claude-plugins")
    assert aggregate is not None
    assert len(aggregate.plugins) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_remove_present_plugin_succeeds() -> None:
    lock = _make_empty_lock()
    await _seed_lock(
        lock,
        name="foo",
        source_url="https://github.com/example/foo",
        version="1.0.0",
        sha="aaa",
    )
    repo = InMemoryGlobalClaudePluginRegistryRepository()
    add = AddGlobalClaudePluginHandler(repo=repo, lock_projection=lock)
    remove = RemoveGlobalClaudePluginHandler(repo=repo)
    await add.handle(name="foo", version="1.0.0")

    result = await remove.handle("foo")

    assert result.name == "foo"
    aggregate = await repo.get_by_id("global-claude-plugins")
    assert aggregate is not None
    assert not aggregate.has("foo")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_remove_missing_plugin_raises_typed_error() -> None:
    repo = InMemoryGlobalClaudePluginRegistryRepository()
    remove = RemoveGlobalClaudePluginHandler(repo=repo)

    with pytest.raises(GlobalClaudePluginNotFoundError):
        await remove.handle("ghost")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_handler_returns_sorted_entries() -> None:
    store = InMemoryProjectionStore()
    projection = GlobalClaudePluginsProjection(store)

    now = datetime.now(UTC).isoformat()
    await projection.on_global_claude_plugin_added(
        {
            "name": "zeta",
            "source_url": "u1",
            "version": "1",
            "resolved_sha": "s1",
            "added_at": now,
        }
    )
    await projection.on_global_claude_plugin_added(
        {
            "name": "alpha",
            "source_url": "u2",
            "version": "2",
            "resolved_sha": "s2",
            "added_at": now,
        }
    )

    handler = ListGlobalClaudePluginsHandler(projection=projection)
    result = await handler.handle()

    assert [e.name for e in result] == ["alpha", "zeta"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_concurrent_add_collapses_to_one_event() -> None:
    """Two concurrent add() calls for the same plugin produce exactly one event."""
    import asyncio

    from event_sourcing import StreamAlreadyExistsError

    lock = _make_empty_lock()
    await _seed_lock(
        lock,
        name="raceglobal",
        source_url="https://github.com/example/raceglobal",
        version="1.0.0",
        sha="aaa",
    )

    class _BarrierRepo(InMemoryGlobalClaudePluginRegistryRepository):
        """Pause both racers inside ``save_new`` so they collide deterministically."""

        def __init__(self) -> None:
            super().__init__()
            self.save_new_calls: int = 0
            self.successful_save_news: int = 0
            self.release = asyncio.Event()

        async def save_new(self, aggregate):  # type: ignore[no-untyped-def]
            # WHY untyped: the aggregate type lives behind a TYPE_CHECKING
            # import in the parent class; importing it eagerly here would be
            # cyclic for the slice module.
            self.save_new_calls += 1
            await self.release.wait()
            try:
                await super().save_new(aggregate)
            except StreamAlreadyExistsError:
                raise
            else:
                self.successful_save_news += 1

    repo = _BarrierRepo()
    add = AddGlobalClaudePluginHandler(repo=repo, lock_projection=lock)

    task_a = asyncio.create_task(add.handle(name="raceglobal", version="1.0.0"))
    task_b = asyncio.create_task(add.handle(name="raceglobal", version="1.0.0"))

    while repo.save_new_calls < 2:
        await asyncio.sleep(0.005)
    repo.release.set()

    result_a = await task_a
    result_b = await task_b

    assert repo.successful_save_news == 1, "exactly one writer must commit save_new"
    assert result_a == result_b
    aggregate = await repo.get_by_id("global-claude-plugins")
    assert aggregate is not None
    assert len(aggregate.plugins) == 1
    assert aggregate.plugins[0].name == "raceglobal"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_projection_remove_drops_entry() -> None:
    store = InMemoryProjectionStore()
    projection = GlobalClaudePluginsProjection(store)

    await projection.on_global_claude_plugin_added(
        {
            "name": "foo",
            "source_url": "u",
            "version": "1",
            "resolved_sha": "s",
            "added_at": datetime.now(UTC).isoformat(),
        }
    )
    await projection.on_global_claude_plugin_removed({"name": "foo"})

    assert await projection.get_by_name("foo") is None
