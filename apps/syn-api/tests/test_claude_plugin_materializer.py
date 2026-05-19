"""Tests for ClaudePluginMaterializer (issue #726, PR2)."""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

import pytest

from syn_adapters.storage.claude_plugin_storage.memory import InMemoryClaudePluginStorage
from syn_api.services.claude_plugin_materializer import (
    WORKSPACE_PLUGIN_ROOT,
    ClaudePluginMaterializer,
)
from syn_domain.contexts.orchestration._shared.claude_plugin_errors import (
    ClaudePluginInvalidName,
)
from syn_domain.contexts.orchestration._shared.resolved_claude_plugin import (
    ResolvedClaudePlugin,
)
from syn_domain.contexts.orchestration.ports.ClaudePluginStoragePort import (
    ClaudePluginFile,
)


def _resolved(name: str, sha: str) -> ResolvedClaudePlugin:
    return ResolvedClaudePlugin(
        name=name,
        source_url=f"https://github.com/example/{name}",
        version="1.0.0",
        resolved_sha=sha,
        tree_storage_prefix=f"memory://claude-plugins/sha256-{sha}",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_for_workspace_returns_empty_when_no_plugins() -> None:
    storage = InMemoryClaudePluginStorage()
    mat = ClaudePluginMaterializer(storage=storage)
    out = await mat.fetch_for_workspace(())
    assert out == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_for_workspace_prefixes_paths_with_plugin_root() -> None:
    storage = InMemoryClaudePluginStorage()
    files = [
        ClaudePluginFile(rel_path=".claude-plugin/plugin.json", content=b'{"name":"hello"}'),
        ClaudePluginFile(rel_path="skills/greet/SKILL.md", content=b"hi"),
    ]
    await storage.upload_tree("sha-hello", files)

    mat = ClaudePluginMaterializer(storage=storage)
    out = await mat.fetch_for_workspace((_resolved("hello", "sha-hello"),))
    paths = sorted(p for p, _ in out)
    assert paths == [
        f"{WORKSPACE_PLUGIN_ROOT}/hello/.claude-plugin/plugin.json",
        f"{WORKSPACE_PLUGIN_ROOT}/hello/skills/greet/SKILL.md",
    ]
    by_path = dict(out)
    assert (
        by_path[f"{WORKSPACE_PLUGIN_ROOT}/hello/.claude-plugin/plugin.json"] == b'{"name":"hello"}'
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_for_workspace_handles_multiple_plugins_independently() -> None:
    storage = InMemoryClaudePluginStorage()
    await storage.upload_tree(
        "sha-a", [ClaudePluginFile(rel_path=".claude-plugin/plugin.json", content=b"a")]
    )
    await storage.upload_tree(
        "sha-b", [ClaudePluginFile(rel_path=".claude-plugin/plugin.json", content=b"b")]
    )

    mat = ClaudePluginMaterializer(storage=storage)
    out = await mat.fetch_for_workspace(
        (_resolved("alpha", "sha-a"), _resolved("beta", "sha-b")),
    )
    paths = sorted(p for p, _ in out)
    assert paths == [
        f"{WORKSPACE_PLUGIN_ROOT}/alpha/.claude-plugin/plugin.json",
        f"{WORKSPACE_PLUGIN_ROOT}/beta/.claude-plugin/plugin.json",
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lru_cache_avoids_refetch_on_repeat_call() -> None:
    storage = InMemoryClaudePluginStorage()
    await storage.upload_tree(
        "sha-cached", [ClaudePluginFile(rel_path=".claude-plugin/plugin.json", content=b"x")]
    )

    fetch_count = {"n": 0}
    real_fetch = storage.fetch_tree

    async def counting_fetch(sha256: str):
        fetch_count["n"] += 1
        return await real_fetch(sha256)

    storage.fetch_tree = counting_fetch  # type: ignore[method-assign]

    mat = ClaudePluginMaterializer(storage=storage)
    plugin = _resolved("cached", "sha-cached")
    await mat.fetch_for_workspace((plugin,))
    await mat.fetch_for_workspace((plugin,))

    assert fetch_count["n"] == 1
    assert mat.cache_size() == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lru_cache_evicts_when_full() -> None:
    storage = InMemoryClaudePluginStorage()
    for i in range(3):
        await storage.upload_tree(
            f"sha-{i}",
            [ClaudePluginFile(rel_path=".claude-plugin/plugin.json", content=str(i).encode())],
        )

    mat = ClaudePluginMaterializer(storage=storage, cache_size=2)
    await mat.fetch_for_workspace((_resolved("p0", "sha-0"),))
    await mat.fetch_for_workspace((_resolved("p1", "sha-1"),))
    await mat.fetch_for_workspace((_resolved("p2", "sha-2"),))

    # Cache holds only the two most recent entries (sha-1, sha-2).
    assert mat.cache_size() == 2


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "hostile_name",
    [
        "../etc/passwd",
        "..",
        "foo/bar",
        "foo\\bar",
        ".hidden",
        "",
        "with\x00null",
        "with\nnewline",
    ],
)
async def test_fetch_for_workspace_rejects_unsafe_plugin_names(hostile_name: str) -> None:
    # Security: a plugin name with path-traversal, separators, leading dot,
    # control characters, or emptiness must be rejected BEFORE any fetch.
    storage = InMemoryClaudePluginStorage()
    await storage.upload_tree(
        "sha-x", [ClaudePluginFile(rel_path=".claude-plugin/plugin.json", content=b"x")]
    )
    fetch_count = {"n": 0}
    real_fetch = storage.fetch_tree

    async def counting_fetch(sha256: str):
        fetch_count["n"] += 1
        return await real_fetch(sha256)

    storage.fetch_tree = counting_fetch  # type: ignore[method-assign]

    plugin = ResolvedClaudePlugin(
        name=hostile_name,
        source_url="https://github.com/example/x",
        version="1.0.0",
        resolved_sha="sha-x",
        tree_storage_prefix="memory://claude-plugins/sha256-sha-x",
    )
    mat = ClaudePluginMaterializer(storage=storage)
    with pytest.raises(ClaudePluginInvalidName):
        await mat.fetch_for_workspace((plugin,))
    # No fetch happened, so nothing was materialized.
    assert fetch_count["n"] == 0
