"""Tests for ListClaudePluginsHandler (issue #726)."""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from datetime import UTC, datetime

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration.slices.list_claude_plugins import (
    ListClaudePluginsHandler,
)
from syn_domain.contexts.orchestration.slices.register_claude_plugin.projection import (
    ClaudePluginLockProjection,
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_returns_sorted_entries() -> None:
    store = InMemoryProjectionStore()
    projection = ClaudePluginLockProjection(store)

    now = datetime.now(UTC).isoformat()
    await projection.on_claude_plugin_registered(
        {
            "source_url": "u-z",
            "version": "1.0.0",
            "name": "zeta",
            "resolved_sha": "s1",
            "tree_storage_prefix": "p1",
            "registered_at": now,
        }
    )
    await projection.on_claude_plugin_registered(
        {
            "source_url": "u-a",
            "version": "1.0.0",
            "name": "alpha",
            "resolved_sha": "s2",
            "tree_storage_prefix": "p2",
            "registered_at": now,
        }
    )
    await projection.on_claude_plugin_registered(
        {
            "source_url": "u-a-2",
            "version": "0.5.0",
            "name": "alpha",
            "resolved_sha": "s3",
            "tree_storage_prefix": "p3",
            "registered_at": now,
        }
    )

    handler = ListClaudePluginsHandler(projection=projection)
    result = await handler.handle()

    assert [(e.name, e.version) for e in result] == [
        ("alpha", "0.5.0"),
        ("alpha", "1.0.0"),
        ("zeta", "1.0.0"),
    ]
