"""Unit tests for InMemorySkillStorage (issue #772)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

# Ensure InMemoryAdapter env-guard passes.
os.environ.setdefault("APP_ENVIRONMENT", "test")

from syn_adapters.storage.skill_storage.memory import (
    InMemorySkillStorage,
    SkillStorageError,
)
from syn_domain.contexts.orchestration.ports.SkillStoragePort import (
    SkillFile,
)
from syn_shared.settings.config import AppEnvironment, Settings


def _mock_settings(env: AppEnvironment) -> Settings:
    """Build a Settings object for the given environment without touching os.environ."""
    return Settings(app_environment=env)  # type: ignore[call-arg]


@pytest.fixture
def storage() -> InMemorySkillStorage:
    return InMemorySkillStorage()


@pytest.fixture
def sample_files() -> list[SkillFile]:
    return [
        SkillFile(
            rel_path="SKILL.md",
            content=b"---\nname: greet\ndescription: says hello\n---\nbody",
        ),
        SkillFile(
            rel_path="scripts/greet.py",
            content=b"print('hello')",
        ),
    ]


@pytest.mark.asyncio
async def test_upload_and_fetch_round_trip(
    storage: InMemorySkillStorage, sample_files: list[SkillFile]
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
    storage: InMemorySkillStorage, sample_files: list[SkillFile]
) -> None:
    sha = "deadbeef" + "0" * 56
    assert await storage.exists(sha) is False
    await storage.upload_tree(sha, sample_files)
    assert await storage.exists(sha) is True


@pytest.mark.asyncio
async def test_prefix_for_matches_upload_prefix(
    storage: InMemorySkillStorage, sample_files: list[SkillFile]
) -> None:
    sha = "cafef00d" + "0" * 56
    result = await storage.upload_tree(sha, sample_files)
    assert storage.prefix_for(sha) == result.storage_prefix


@pytest.mark.asyncio
async def test_upload_empty_tree_raises(storage: InMemorySkillStorage) -> None:
    with pytest.raises(SkillStorageError):
        await storage.upload_tree("0" * 64, [])


@pytest.mark.asyncio
async def test_fetch_unknown_sha_raises(storage: InMemorySkillStorage) -> None:
    with pytest.raises(SkillStorageError):
        await storage.fetch_tree("missing")


@pytest.mark.asyncio
async def test_uploaded_tree_is_immutable_to_caller_mutation(
    storage: InMemorySkillStorage, sample_files: list[SkillFile]
) -> None:
    sha = "1" * 64
    await storage.upload_tree(sha, sample_files)
    # Mutate the input list after upload.
    sample_files.append(SkillFile(rel_path="rogue", content=b"x"))
    fetched = await storage.fetch_tree(sha)
    assert len(fetched) == 2


def test_memory_adapter_environment_guard() -> None:
    """InMemorySkillStorage must refuse to instantiate outside test/offline mode (ADR-060)."""
    from syn_adapters.in_memory import InMemoryAdapterError

    try:
        with (
            patch(
                "syn_adapters.in_memory.get_settings",
                return_value=_mock_settings(AppEnvironment.PRODUCTION),
            ),
            pytest.raises(InMemoryAdapterError, match="test/offline only"),
        ):
            InMemorySkillStorage()
    finally:
        from syn_shared.settings import reset_settings

        reset_settings()
