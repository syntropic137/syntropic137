# See ADR-066: register slice tests use the in-memory storage and registration
# repository directly; no fetcher exists in this layer (issue #772).
"""Tests for RegisterSkillHandler (issue #772)."""

from __future__ import annotations

import os

# Must be set before any syn_* imports for in-memory adapter guard.
os.environ.setdefault("APP_ENVIRONMENT", "test")

import pytest

from syn_adapters.storage.in_memory_skill_repositories import (
    InMemorySkillRegistrationRepository,
)
from syn_adapters.storage.skill_storage.memory import InMemorySkillStorage
from syn_domain.contexts.orchestration._shared.skill_errors import (
    SkillInvalidPath,
    SkillManifestInvalid,
    SkillManifestMissing,
)
from syn_domain.contexts.orchestration.ports.SkillStoragePort import SkillFile
from syn_domain.contexts.orchestration.slices.register_skill import RegisterSkillHandler

SKILL_MD = b"""---
name: code-review
description: Review diffs for correctness bugs.
---

# Code Review

Instructions here.
"""


def _make_files(name: str = "code-review", extra: str = "hi") -> list[SkillFile]:
    """Build a minimal but valid skill tree."""
    return [
        SkillFile(
            rel_path="SKILL.md",
            content=(f"---\nname: {name}\ndescription: {extra}\n---\n\n# {name}\n").encode(),
        ),
    ]


def _make_handler() -> tuple[
    RegisterSkillHandler,
    InMemorySkillStorage,
    InMemorySkillRegistrationRepository,
]:
    storage = InMemorySkillStorage()
    repo = InMemorySkillRegistrationRepository()
    handler = RegisterSkillHandler(storage=storage, repo=repo)
    return handler, storage, repo


@pytest.fixture
def handler() -> RegisterSkillHandler:
    made, _storage, _repo = _make_handler()
    return made


@pytest.mark.unit
@pytest.mark.asyncio
async def test_register_skill_happy_path(handler: RegisterSkillHandler) -> None:
    result = await handler.handle(
        source_url="https://github.com/acme/agent-skills",
        version="v2.0.0",
        skill_name=None,
        files=[SkillFile(rel_path="SKILL.md", content=SKILL_MD)],
    )
    assert result.skill_name == "code-review"  # frontmatter name wins when no override
    assert len(result.resolved_sha) == 64


@pytest.mark.unit
@pytest.mark.asyncio
async def test_missing_skill_md_rejected(handler: RegisterSkillHandler) -> None:
    with pytest.raises(SkillManifestMissing):
        await handler.handle(
            source_url="https://github.com/acme/agent-skills",
            version="v2.0.0",
            skill_name="x",
            files=[SkillFile(rel_path="README.md", content=b"nope")],
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_frontmatter_without_name_rejected(handler: RegisterSkillHandler) -> None:
    bad = b"---\ndescription: no name here\n---\nbody"
    with pytest.raises(SkillManifestInvalid, match="frontmatter must declare 'name'"):
        await handler.handle(
            source_url="https://github.com/acme/agent-skills",
            version="v2.0.0",
            skill_name=None,
            files=[SkillFile(rel_path="SKILL.md", content=bad)],
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_explicit_skill_name_wins_over_frontmatter() -> None:
    handler, _storage, _repo = _make_handler()

    result = await handler.handle(
        source_url="https://github.com/acme/agent-skills",
        version="v2.0.0",
        skill_name="override-name",
        files=[SkillFile(rel_path="SKILL.md", content=SKILL_MD)],
    )
    assert result.skill_name == "override-name"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cache_hit_skips_redundant_upload() -> None:
    """Re-registering a different (source_url, version) sharing a tree sha skips upload."""

    class _CountingStorage(InMemorySkillStorage):
        """Track ``upload_tree`` invocations so the test can assert call counts."""

        def __init__(self) -> None:
            super().__init__()
            self.upload_calls: int = 0

        async def upload_tree(
            self,
            sha256: str,
            files: list[SkillFile],
        ) -> object:
            self.upload_calls += 1
            return await super().upload_tree(sha256, files)

    storage = _CountingStorage()
    repo = InMemorySkillRegistrationRepository()
    handler = RegisterSkillHandler(storage=storage, repo=repo)

    files = _make_files(name="cached")

    # First register: cache miss, must upload exactly once.
    await handler.handle(
        source_url="https://github.com/example/cached-a",
        version="1.0.0",
        skill_name="cached",
        files=files,
    )
    assert storage.upload_calls == 1

    # Second register: same tree sha (identical files), different
    # (source_url, version). Upload count must stay at 1 because exists(sha)
    # returns True.
    await handler.handle(
        source_url="https://github.com/example/cached-b",
        version="1.0.0",
        skill_name="cached",
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
        skill_name="foo",
        files=_make_files(name="foo"),
    )
    second = await handler.handle(
        source_url="https://github.com/example/foo",
        version="2.0.0",
        skill_name="foo",
        files=_make_files(name="foo"),
    )

    assert first == second


@pytest.mark.unit
@pytest.mark.asyncio
async def test_hostile_rel_path_rejected() -> None:
    handler, _storage, _repo = _make_handler()

    with pytest.raises(SkillInvalidPath):
        await handler.handle(
            source_url="https://github.com/example/hostile",
            version="1.0.0",
            skill_name="hostile",
            files=[
                SkillFile(rel_path="SKILL.md", content=SKILL_MD),
                SkillFile(rel_path="../../etc/passwd", content=b"nope"),
            ],
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lock_projection_reflects_registered_skill() -> None:
    """Apply the emitted event to the projection and confirm it is queryable."""
    from datetime import UTC, datetime

    from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
    from syn_domain.contexts.orchestration.slices.register_skill.projection import (
        SkillLockProjection,
    )

    handler, _storage, _repo = _make_handler()
    result = await handler.handle(
        source_url="https://github.com/example/baz",
        version="3.0.0",
        skill_name="baz",
        files=_make_files(name="baz"),
    )

    store = InMemoryProjectionStore()
    projection = SkillLockProjection(store)
    await projection.on_skill_registered(
        {
            "source_url": result.source_url,
            "version": result.version,
            "resolved_sha": result.resolved_sha,
            "skill_name": result.skill_name,
            "tree_storage_prefix": result.tree_storage_prefix,
            "registered_at": datetime.now(UTC).isoformat(),
        }
    )

    entry = await projection.get(result.source_url, result.version, result.skill_name)
    assert entry is not None
    assert entry.skill_name == "baz"
    assert entry.resolved_sha == result.resolved_sha
    assert entry.tree_storage_prefix == result.tree_storage_prefix
