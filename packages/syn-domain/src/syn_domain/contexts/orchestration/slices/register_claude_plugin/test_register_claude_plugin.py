# See ADR-066: register slice tests use the in-memory storage and registration
# repository directly; no fetcher exists in this layer after the #726 Phase A
# redesign.
"""Tests for RegisterClaudePluginHandler (issue #726, Phase A redesign)."""

from __future__ import annotations

import os

# Must be set before any syn_* imports for in-memory adapter guard.
os.environ.setdefault("APP_ENVIRONMENT", "test")

import json

import pytest

from syn_adapters.storage.claude_plugin_storage.memory import InMemoryClaudePluginStorage
from syn_adapters.storage.in_memory_claude_plugin_repositories import (
    InMemoryClaudePluginRegistrationRepository,
)
from syn_domain.contexts.orchestration._shared.claude_plugin_errors import (
    ClaudePluginManifestMissing,
)
from syn_domain.contexts.orchestration.ports.ClaudePluginStoragePort import (
    ClaudePluginFile,
)
from syn_domain.contexts.orchestration.slices.register_claude_plugin import (
    RegisterClaudePluginHandler,
)


def _make_files(name: str = "hello-world", extra: str = "hi") -> list[ClaudePluginFile]:
    """Build a minimal but valid claude plugin tree."""
    return [
        ClaudePluginFile(
            rel_path=".claude-plugin/plugin.json",
            content=json.dumps({"name": name, "version": "0.0.1"}).encode("utf-8"),
        ),
        ClaudePluginFile(
            rel_path="skills/hello/SKILL.md",
            content=f"# Hello\n{extra}\n".encode(),
        ),
    ]


def _manifest(name: str) -> dict[str, object]:
    return {"name": name, "version": "0.0.1"}


def _make_handler() -> tuple[
    RegisterClaudePluginHandler,
    InMemoryClaudePluginStorage,
    InMemoryClaudePluginRegistrationRepository,
]:
    storage = InMemoryClaudePluginStorage()
    repo = InMemoryClaudePluginRegistrationRepository()
    handler = RegisterClaudePluginHandler(storage=storage, repo=repo)
    return handler, storage, repo


@pytest.mark.unit
@pytest.mark.asyncio
async def test_happy_path_registers_plugin() -> None:
    handler, storage, _repo = _make_handler()

    result = await handler.handle(
        source_url="https://github.com/example/hello-world",
        version="1.0.0",
        name="hello-world",
        manifest=_manifest("hello-world"),
        files=_make_files(name="hello-world"),
    )

    assert result.name == "hello-world"
    assert result.source_url == "https://github.com/example/hello-world"
    assert result.version == "1.0.0"
    assert result.resolved_sha
    assert result.tree_storage_prefix
    assert storage.count == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cache_hit_skips_redundant_upload() -> None:
    """Re-registering a different (source_url, version) sharing a tree sha skips upload."""

    class _CountingStorage(InMemoryClaudePluginStorage):
        """Track ``upload_tree`` invocations so the test can assert call counts."""

        def __init__(self) -> None:
            super().__init__()
            self.upload_calls: int = 0

        async def upload_tree(
            self,
            sha256: str,
            files: list[ClaudePluginFile],
        ) -> object:
            self.upload_calls += 1
            return await super().upload_tree(sha256, files)

    storage = _CountingStorage()
    repo = InMemoryClaudePluginRegistrationRepository()
    handler = RegisterClaudePluginHandler(storage=storage, repo=repo)

    files = _make_files(name="cached")

    # First register: cache miss, must upload exactly once.
    await handler.handle(
        source_url="https://github.com/example/cached-a",
        version="1.0.0",
        name="cached",
        manifest=_manifest("cached"),
        files=files,
    )
    assert storage.upload_calls == 1

    # Second register: same tree sha (identical files), different
    # (source_url, version). Upload count must stay at 1 because exists(sha)
    # returns True.
    await handler.handle(
        source_url="https://github.com/example/cached-b",
        version="1.0.0",
        name="cached",
        manifest=_manifest("cached"),
        files=files,
    )
    assert storage.upload_calls == 1, "upload_tree must not be called on cache hit"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_idempotent_re_register_returns_same_result() -> None:
    handler, _storage, _repo = _make_handler()

    first = await handler.handle(
        source_url="https://github.com/example/foo",
        version="2.0.0",
        name="foo",
        manifest=_manifest("foo"),
        files=_make_files(name="foo"),
    )
    second = await handler.handle(
        source_url="https://github.com/example/foo",
        version="2.0.0",
        name="foo",
        manifest=_manifest("foo"),
        files=_make_files(name="foo"),
    )

    assert first == second


@pytest.mark.unit
@pytest.mark.asyncio
async def test_manifest_missing_raises_typed_error() -> None:
    handler, _storage, _repo = _make_handler()

    with pytest.raises(ClaudePluginManifestMissing):
        await handler.handle(
            source_url="https://github.com/example/no-manifest",
            version="1.0.0",
            name="no-manifest",
            manifest={},
            files=[ClaudePluginFile(rel_path="README.md", content=b"hello")],
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lock_projection_reflects_registered_plugin() -> None:
    """Apply the emitted event to the projection and confirm it is queryable."""
    from datetime import UTC, datetime

    from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
    from syn_domain.contexts.orchestration.slices.register_claude_plugin.projection import (
        ClaudePluginLockProjection,
    )

    handler, _storage, _repo = _make_handler()
    result = await handler.handle(
        source_url="https://github.com/example/baz",
        version="3.0.0",
        name="baz",
        manifest=_manifest("baz"),
        files=_make_files(name="baz"),
    )

    store = InMemoryProjectionStore()
    projection = ClaudePluginLockProjection(store)
    await projection.on_claude_plugin_registered(
        {
            "source_url": result.source_url,
            "version": result.version,
            "resolved_sha": result.resolved_sha,
            "name": result.name,
            "tree_storage_prefix": result.tree_storage_prefix,
            "registered_at": datetime.now(UTC).isoformat(),
        }
    )

    entry = await projection.get_by_source_version_name(
        result.source_url, result.version, result.name
    )
    assert entry is not None
    assert entry.name == "baz"
    assert entry.resolved_sha == result.resolved_sha
    assert entry.tree_storage_prefix == result.tree_storage_prefix
