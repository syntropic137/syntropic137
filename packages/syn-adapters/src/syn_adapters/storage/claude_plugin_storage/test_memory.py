"""Unit tests for InMemoryClaudePluginStorage (issue #726)."""

from __future__ import annotations

import os

import pytest

# Ensure InMemoryAdapter env-guard passes.
os.environ.setdefault("APP_ENVIRONMENT", "test")

from syn_adapters.storage.claude_plugin_storage.memory import (
    ClaudePluginStorageError,
    InMemoryClaudePluginStorage,
)
from syn_domain.contexts.orchestration.ports.ClaudePluginStoragePort import (
    ClaudePluginFile,
)

# Marked at module scope: these files were never COLLECTED before the
# testpaths change in this commit, so nothing here had a reason to carry a
# marker. Unmarked now means collected but run by no CI job, which the
# census gate correctly refuses.
pytestmark = pytest.mark.unit


@pytest.fixture
def storage() -> InMemoryClaudePluginStorage:
    return InMemoryClaudePluginStorage()


@pytest.fixture
def sample_files() -> list[ClaudePluginFile]:
    return [
        ClaudePluginFile(
            rel_path=".claude-plugin/plugin.json",
            content=b'{"name": "test", "version": "0.0.1"}',
        ),
        ClaudePluginFile(
            rel_path="skills/greet/SKILL.md",
            content=b"---\nname: greet\n---\nbody",
        ),
    ]


@pytest.mark.asyncio
async def test_upload_and_fetch_round_trip(
    storage: InMemoryClaudePluginStorage, sample_files: list[ClaudePluginFile]
) -> None:
    sha = "abc123" + "0" * 58
    result = await storage.upload_tree(sha, sample_files)

    assert result.sha256 == sha
    assert result.file_count == 2
    assert result.total_size_bytes == sum(len(f.content) for f in sample_files)

    fetched = await storage.fetch_tree(sha)
    by_path = {f.rel_path: f.content for f in fetched}
    assert by_path == {f.rel_path: f.content for f in sample_files}


@pytest.mark.asyncio
async def test_exists_returns_true_after_upload(
    storage: InMemoryClaudePluginStorage, sample_files: list[ClaudePluginFile]
) -> None:
    sha = "deadbeef" + "0" * 56
    assert await storage.exists(sha) is False
    await storage.upload_tree(sha, sample_files)
    assert await storage.exists(sha) is True


@pytest.mark.asyncio
async def test_upload_empty_tree_raises(storage: InMemoryClaudePluginStorage) -> None:
    with pytest.raises(ClaudePluginStorageError):
        await storage.upload_tree("0" * 64, [])


@pytest.mark.asyncio
async def test_fetch_unknown_sha_raises(storage: InMemoryClaudePluginStorage) -> None:
    with pytest.raises(ClaudePluginStorageError):
        await storage.fetch_tree("missing")


@pytest.mark.asyncio
async def test_uploaded_tree_is_immutable_to_caller_mutation(
    storage: InMemoryClaudePluginStorage, sample_files: list[ClaudePluginFile]
) -> None:
    sha = "1" * 64
    await storage.upload_tree(sha, sample_files)
    # Mutate the input list after upload.
    sample_files.append(ClaudePluginFile(rel_path="rogue", content=b"x"))
    fetched = await storage.fetch_tree(sha)
    assert len(fetched) == 2
