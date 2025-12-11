"""Tests for object storage adapters.

Tests LocalStorage and the storage factory.
SupabaseStorage tests require Supabase to be running.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from aef_adapters.object_storage import (
    LocalStorage,
    ObjectNotFoundError,
    StorageProtocol,
    get_storage,
    reset_storage,
)
from aef_shared.settings.storage import StorageProvider, StorageSettings


class TestLocalStorage:
    """Tests for LocalStorage adapter."""

    @pytest.fixture
    def temp_dir(self) -> Path:
        """Create a temporary directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def storage(self, temp_dir: Path) -> LocalStorage:
        """Create a LocalStorage instance."""
        return LocalStorage(base_path=temp_dir)

    @pytest.mark.asyncio
    async def test_upload_and_download(self, storage: LocalStorage) -> None:
        """Test basic upload and download."""
        content = b"Hello, World!"
        key = "test.txt"

        # Upload
        result = await storage.upload(key, content)
        assert result.key == key
        assert result.size_bytes == len(content)
        assert result.etag is not None

        # Download
        downloaded = await storage.download(key)
        assert downloaded == content

    @pytest.mark.asyncio
    async def test_upload_with_subdirectories(self, storage: LocalStorage) -> None:
        """Test upload with nested path."""
        content = b"Nested content"
        key = "workflows/123/bundles/abc/report.md"

        result = await storage.upload(key, content)
        assert result.key == key

        downloaded = await storage.download(key)
        assert downloaded == content

    @pytest.mark.asyncio
    async def test_download_not_found(self, storage: LocalStorage) -> None:
        """Test download of non-existent object."""
        with pytest.raises(ObjectNotFoundError) as exc_info:
            await storage.download("nonexistent.txt")
        assert "nonexistent.txt" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_exists(self, storage: LocalStorage) -> None:
        """Test existence check."""
        key = "exists.txt"
        assert await storage.exists(key) is False

        await storage.upload(key, b"content")
        assert await storage.exists(key) is True

    @pytest.mark.asyncio
    async def test_delete(self, storage: LocalStorage) -> None:
        """Test deletion."""
        key = "deleteme.txt"
        await storage.upload(key, b"content")
        assert await storage.exists(key) is True

        result = await storage.delete(key)
        assert result is True
        assert await storage.exists(key) is False

        # Delete non-existent
        result = await storage.delete("nonexistent.txt")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_object_info(self, storage: LocalStorage) -> None:
        """Test getting object metadata."""
        key = "info.txt"
        content = b"Some content here"
        await storage.upload(key, content)

        info = await storage.get_object_info(key)
        assert info is not None
        assert info.key == key
        assert info.size_bytes == len(content)
        assert info.content_type == "text/plain"

        # Non-existent
        info = await storage.get_object_info("nonexistent.txt")
        assert info is None

    @pytest.mark.asyncio
    async def test_list_objects(self, storage: LocalStorage) -> None:
        """Test listing objects."""
        # Upload some files
        await storage.upload("dir1/file1.txt", b"content1")
        await storage.upload("dir1/file2.txt", b"content2")
        await storage.upload("dir2/file3.txt", b"content3")

        # List all
        result = await storage.list_objects()
        assert len(result.objects) == 3

        # List with prefix
        result = await storage.list_objects("dir1/")
        assert len(result.objects) == 2

    @pytest.mark.asyncio
    async def test_path_traversal_protection(self, storage: LocalStorage) -> None:
        """Test that path traversal is prevented."""
        with pytest.raises(ValueError, match="path traversal"):
            await storage.upload("../../../etc/passwd", b"malicious")

    @pytest.mark.asyncio
    async def test_presigned_url(self, storage: LocalStorage) -> None:
        """Test presigned URL generation (returns file:// URL for local)."""
        key = "presigned.txt"
        await storage.upload(key, b"content")

        url = await storage.get_presigned_url(key)
        assert url.startswith("file://")
        assert key in url

    def test_provider_property(self, storage: LocalStorage) -> None:
        """Test provider property."""
        assert storage.provider == StorageProvider.LOCAL

    def test_bucket_name_property(self, storage: LocalStorage, temp_dir: Path) -> None:
        """Test bucket_name property."""
        # Handle macOS symlink resolution (/var -> /private/var)
        assert storage.bucket_name == str(temp_dir.resolve())


class TestStorageSettings:
    """Tests for StorageSettings."""

    def test_default_settings(self) -> None:
        """Test default settings."""
        settings = StorageSettings()
        assert settings.provider == StorageProvider.LOCAL
        assert settings.local_path == Path(".artifacts")
        assert settings.is_local is True
        assert settings.is_supabase is False
        assert settings.is_configured is True

    def test_supabase_settings_validation(self) -> None:
        """Test that Supabase settings require URL and key."""
        with pytest.raises(ValueError, match="Supabase storage requires"):
            StorageSettings(provider=StorageProvider.SUPABASE)

    def test_supabase_settings_valid(self) -> None:
        """Test valid Supabase settings."""
        settings = StorageSettings(
            provider=StorageProvider.SUPABASE,
            supabase_url="https://example.supabase.co",
            supabase_key="secret-key",
        )
        assert settings.is_supabase is True
        assert settings.is_configured is True

    def test_max_file_size_bytes(self) -> None:
        """Test max file size conversion."""
        settings = StorageSettings(max_file_size_mb=100)
        assert settings.max_file_size_bytes == 100 * 1024 * 1024


class TestStorageFactory:
    """Tests for get_storage factory."""

    @pytest.fixture(autouse=True)
    def reset_factory(self) -> None:
        """Reset storage factory before each test."""
        reset_storage()

    @pytest.mark.asyncio
    async def test_get_storage_local(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test factory returns LocalStorage by default."""
        monkeypatch.setenv("AEF_STORAGE_PROVIDER", "local")
        reset_storage()

        storage = await get_storage()
        assert isinstance(storage, LocalStorage)
        assert storage.provider == StorageProvider.LOCAL

    @pytest.mark.asyncio
    async def test_get_storage_cached(self) -> None:
        """Test that factory caches the storage instance."""
        storage1 = await get_storage()
        storage2 = await get_storage()
        assert storage1 is storage2


class TestStorageProtocol:
    """Tests for StorageProtocol runtime checking."""

    def test_local_storage_implements_protocol(self, tmp_path: Path) -> None:
        """Test that LocalStorage implements StorageProtocol."""
        storage = LocalStorage(base_path=tmp_path)
        assert isinstance(storage, StorageProtocol)


class TestArtifactBundleStorage:
    """Tests for ArtifactBundle storage integration."""

    @pytest.fixture
    def temp_dir(self) -> Path:
        """Create a temporary directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def storage(self, temp_dir: Path) -> LocalStorage:
        """Create a LocalStorage instance."""
        return LocalStorage(base_path=temp_dir)

    @pytest.mark.asyncio
    async def test_bundle_save_and_load(self, storage: LocalStorage) -> None:
        """Test saving and loading artifact bundle."""
        from aef_adapters.artifacts.bundle import ArtifactBundle, ArtifactType

        # Create bundle with files
        bundle = ArtifactBundle(
            bundle_id="test-bundle",
            phase_id="research",
            workflow_id="wf-123",
        )
        bundle.add_file(
            path=Path("report.md"),
            content=b"# Research Report\n\nFindings...",
            artifact_type=ArtifactType.MARKDOWN,
            title="Research Report",
        )
        bundle.add_file(
            path=Path("data/results.json"),
            content=b'{"key": "value"}',
            artifact_type=ArtifactType.JSON,
        )

        # Save to storage
        keys = await bundle.save_to_storage(storage)
        assert len(keys) == 3  # 2 files + manifest

        # Load from storage
        loaded = await ArtifactBundle.load_from_storage(
            storage,
            bundle_id="test-bundle",
            workflow_id="wf-123",
        )

        assert loaded.bundle_id == bundle.bundle_id
        assert loaded.phase_id == bundle.phase_id
        assert loaded.file_count == bundle.file_count
        assert loaded.files[0].text_content == bundle.files[0].text_content

    @pytest.mark.asyncio
    async def test_bundle_storage_prefix(self) -> None:
        """Test storage prefix generation."""
        from aef_adapters.artifacts.bundle import ArtifactBundle

        bundle = ArtifactBundle(
            bundle_id="abc",
            phase_id="research",
            workflow_id="wf-123",
            session_id="sess-456",
        )

        prefix = bundle.get_storage_prefix()
        assert "workflows/wf-123" in prefix
        assert "sessions/sess-456" in prefix
        assert "bundles/abc" in prefix
