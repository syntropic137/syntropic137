"""Tests for ShowClaudePluginHandler (issue #726)."""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from datetime import UTC, datetime

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration.slices.register_claude_plugin.projection import (
    ClaudePluginLockProjection,
)
from syn_domain.contexts.orchestration.slices.show_claude_plugin import (
    ClaudePluginNotFoundError,
    ShowClaudePluginHandler,
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_show_returns_entry_when_present() -> None:
    store = InMemoryProjectionStore()
    projection = ClaudePluginLockProjection(store)
    await projection.on_claude_plugin_registered(
        {
            "source_url": "u",
            "version": "1.0.0",
            "name": "foo",
            "resolved_sha": "sha",
            "tree_storage_prefix": "prefix",
            "registered_at": datetime.now(UTC).isoformat(),
        }
    )
    handler = ShowClaudePluginHandler(projection=projection)

    entry = await handler.handle("foo", "1.0.0")

    assert entry.name == "foo"
    assert entry.version == "1.0.0"
    assert entry.resolved_sha == "sha"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_show_raises_when_missing() -> None:
    store = InMemoryProjectionStore()
    projection = ClaudePluginLockProjection(store)
    handler = ShowClaudePluginHandler(projection=projection)

    with pytest.raises(ClaudePluginNotFoundError):
        await handler.handle("ghost", "0.0.1")
