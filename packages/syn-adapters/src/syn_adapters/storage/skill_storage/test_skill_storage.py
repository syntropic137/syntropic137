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


# ---------------------------------------------------------------------------
# Storage size reporting (issue #772, spec D6)
#
# Eviction is deliberately not implemented, so the size numbers are the only
# thing keeping that a measured decision. The MinIO adapter is the production
# path, so it is tested against a stubbed object store rather than trusted.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_stats_count_trees_files_and_bytes(
    storage: InMemorySkillStorage, sample_files: list[SkillFile]
) -> None:
    await storage.upload_tree("aaa", sample_files)

    stats = await storage.stats()

    assert stats.skill_count == 1
    assert stats.object_count == len(sample_files)
    assert stats.total_bytes == sum(len(f.content) for f in sample_files)
    assert stats.truncated is False


@pytest.mark.asyncio
async def test_memory_stats_are_zero_for_an_empty_store(
    storage: InMemorySkillStorage,
) -> None:
    stats = await storage.stats()

    assert (stats.object_count, stats.total_bytes, stats.skill_count) == (0, 0, 0)


class _StubObjectStore:
    """Minimal stand-in for MinioStorage.list_objects."""

    def __init__(self, keys_and_sizes: list[tuple[str, int]], *, truncated: bool = False) -> None:
        self._keys_and_sizes = keys_and_sizes
        self._truncated = truncated
        self.bucket_name = "test-bucket"

    async def list_objects(
        self, prefix: str = "", *, max_keys: int = 1000, continuation_token: str | None = None
    ) -> object:
        from syn_adapters.object_storage.protocol import ListResult, StorageObject

        return ListResult(
            objects=[
                StorageObject(key=key, size_bytes=size)
                for key, size in self._keys_and_sizes
                if key.startswith(prefix)
            ],
            is_truncated=self._truncated,
            prefix=prefix,
        )


@pytest.mark.asyncio
async def test_minio_stats_group_objects_into_distinct_trees() -> None:
    from syn_adapters.storage.skill_storage.minio import MinioSkillStorage

    store = _StubObjectStore(
        [
            ("skills/sha256-aaa/manifest.json", 10),
            ("skills/sha256-aaa/files/SKILL.md", 100),
            ("skills/sha256-bbb/manifest.json", 10),
            ("skills/sha256-bbb/files/SKILL.md", 200),
            # A key outside the skills prefix must not be counted.
            ("artifacts/other.bin", 9999),
        ]
    )
    adapter = MinioSkillStorage(store)  # type: ignore[arg-type]

    stats = await adapter.stats()

    assert stats.skill_count == 2
    assert stats.object_count == 4
    assert stats.total_bytes == 320


@pytest.mark.asyncio
async def test_minio_stats_report_a_truncated_listing_rather_than_hiding_it() -> None:
    """A capped total silently reported as complete is worse than no total."""
    from syn_adapters.storage.skill_storage.minio import MinioSkillStorage

    store = _StubObjectStore([("skills/sha256-aaa/manifest.json", 10)], truncated=True)
    adapter = MinioSkillStorage(store)  # type: ignore[arg-type]

    stats = await adapter.stats()

    assert stats.truncated is True
