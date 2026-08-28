# See ADR-066: register slice tests use the in-memory storage and registration
# repository directly; no fetcher exists in this layer after the #726 Phase A
# redesign.
"""Tests for RegisterClaudePluginHandler (issue #726, Phase A redesign)."""

from __future__ import annotations

import os
from datetime import UTC, datetime

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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sha256_version_must_name_the_content_it_carries() -> None:
    """A sha256- version is a content commitment, not a label.

    register_skill has enforced this since #772. This slice pins content the
    same way and did not, so a caller could register arbitrary content under
    a version naming another tree's hash, and every later install resolving
    that triple would receive the substituted content.
    """
    from syn_domain.contexts.orchestration import ClaudePluginVersionHashMismatch

    handler, storage, _repo = _make_handler()

    with pytest.raises(ClaudePluginVersionHashMismatch) as exc_info:
        await handler.handle(
            source_url="https://github.com/example/hello-world",
            version="sha256-" + "0" * 64,
            name="hello-world",
            manifest=_manifest("hello-world"),
            files=_make_files(name="hello-world"),
        )

    assert "claims a content hash" in str(exc_info.value)
    # Nothing was uploaded: the refusal precedes any write.
    assert storage.count == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sha256_version_matching_the_tree_is_accepted() -> None:
    handler, _storage, _repo = _make_handler()
    files = _make_files(name="hello-world")

    # Register once with a plain version to learn the tree's real hash.
    probe = await handler.handle(
        source_url="https://github.com/example/hello-world",
        version="1.0.0",
        name="hello-world",
        manifest=_manifest("hello-world"),
        files=files,
    )

    result = await handler.handle(
        source_url="https://github.com/example/hello-world",
        version=f"sha256-{probe.resolved_sha}",
        name="hello-world",
        manifest=_manifest("hello-world"),
        files=files,
    )

    assert result.resolved_sha == probe.resolved_sha


@pytest.mark.unit
@pytest.mark.asyncio
async def test_hash_check_precedes_the_idempotency_fast_path() -> None:
    """Checking after the fast path would leave the first registration unguarded.

    The first registration of a triple is the only one that matters: every
    later resolve of it returns whatever that first call stored.
    """
    from syn_domain.contexts.orchestration import ClaudePluginVersionHashMismatch

    handler, _storage, _repo = _make_handler()
    honest = _make_files(name="hello-world", extra="original")
    forged = _make_files(name="hello-world", extra="substituted")

    probe = await handler.handle(
        source_url="https://github.com/example/hello-world",
        version="1.0.0",
        name="hello-world",
        manifest=_manifest("hello-world"),
        files=honest,
    )
    pinned = f"sha256-{probe.resolved_sha}"

    await handler.handle(
        source_url="https://github.com/example/hello-world",
        version=pinned,
        name="hello-world",
        manifest=_manifest("hello-world"),
        files=honest,
    )

    # Same triple, different bytes. The existing aggregate must not let it through.
    with pytest.raises(ClaudePluginVersionHashMismatch):
        await handler.handle(
            source_url="https://github.com/example/hello-world",
            version=pinned,
            name="hello-world",
            manifest=_manifest("hello-world"),
            files=forged,
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_record_poisoned_before_the_guard_existed_is_refused() -> None:
    """The fast path re-checks the STORED sha, not only the submitted tree.

    A record written before the guard existed can carry a pinned version whose
    resolved_sha does not match it. Returning it from the fast path would keep
    serving that substituted content forever, and an honest re-registration
    would launder it back into circulation.
    """
    from syn_domain.contexts.orchestration import ClaudePluginVersionHashMismatch
    from syn_domain.contexts.orchestration.domain.aggregate_claude_plugin_registration.ClaudePluginRegistrationAggregate import (
        ClaudePluginRegistrationAggregate,
    )
    from syn_domain.contexts.orchestration.domain.events.ClaudePluginRegisteredEvent import (
        ClaudePluginRegisteredEvent,
    )

    handler, _storage, repo = _make_handler()
    files = _make_files(name="hello-world")
    source_url = "https://github.com/example/hello-world"
    honest_sha = "a" * 64
    version = f"sha256-{honest_sha}"

    stream_id = ClaudePluginRegistrationAggregate.compute_stream_id(
        source_url, version, "hello-world"
    )

    # Simulate history: a pinned version stored against different content.
    poisoned = ClaudePluginRegistrationAggregate()
    poisoned._initialize(stream_id)
    poisoned._apply(
        ClaudePluginRegisteredEvent(
            source_url=source_url,
            version=version,
            resolved_sha="b" * 64,
            name="hello-world",
            tree_storage_prefix="plugins/sha256-" + "b" * 64,
            manifest=_manifest("hello-world"),
            registered_at=datetime.now(UTC),
        )
    )
    await repo.save(poisoned)

    with pytest.raises(ClaudePluginVersionHashMismatch):
        await handler.handle(
            source_url=source_url,
            version=version,
            name="hello-world",
            manifest=_manifest("hello-world"),
            files=files,
        )


@pytest.mark.unit
def test_aggregate_refuses_a_pin_contradicting_its_resolved_sha() -> None:
    """The handler is not the only way in, so the aggregate refuses too."""
    from syn_domain.contexts.orchestration.domain.aggregate_claude_plugin_registration.ClaudePluginRegistrationAggregate import (
        ClaudePluginRegistrationAggregate,
    )
    from syn_domain.contexts.orchestration.domain.commands.RegisterClaudePluginCommand import (
        RegisterClaudePluginCommand,
    )

    aggregate = ClaudePluginRegistrationAggregate()

    with pytest.raises(ValueError, match="does not match resolved_sha"):
        aggregate.register(
            RegisterClaudePluginCommand(
                aggregate_id="plugin-1",
                source_url="https://github.com/example/hello-world",
                version="sha256-" + "a" * 64,
                resolved_sha="b" * 64,
                name="hello-world",
                tree_storage_prefix="plugins/x",
                manifest=_manifest("hello-world"),
            )
        )

    assert not aggregate.get_uncommitted_events()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ordinary_versions_are_not_rehashed_on_a_duplicate_register() -> None:
    """Hashing a tree is bounded only by the API's tree size limit.

    Pinned duplicates must be rehashed to be checked; ordinary tags and
    branches must not pay that cost on every re-register.
    """
    from unittest.mock import patch

    handler, _storage, _repo = _make_handler()
    files = _make_files(name="hello-world")
    kwargs = {
        "source_url": "https://github.com/example/hello-world",
        "version": "1.0.0",
        "name": "hello-world",
        "manifest": _manifest("hello-world"),
        "files": files,
    }

    await handler.handle(**kwargs)

    module = "syn_domain.contexts.orchestration.slices.register_claude_plugin.RegisterClaudePluginHandler._compute_tree_sha"
    with patch(module) as spy:
        await handler.handle(**kwargs)

    spy.assert_not_called()
