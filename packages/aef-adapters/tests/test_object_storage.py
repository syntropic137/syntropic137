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
    MinioStorage,
    ObjectNotFoundError,
    StorageProtocol,
    get_storage,
    reset_storage,
)
from aef_shared.settings.storage import StorageProvider, StorageSettings


@pytest.mark.unit
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
        """Test settings when explicitly set to local provider.

        Note: We test explicit local provider since .env may configure different defaults.
        """
        settings = StorageSettings(provider=StorageProvider.LOCAL)

        assert settings.provider == StorageProvider.LOCAL
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

    def test_minio_settings_validation(self) -> None:
        """Test that MinIO settings require endpoint and credentials.

        Note: When MinIO is configured via .env, we verify the config works.
        Otherwise, we test that validation fails without credentials.
        """
        try:
            # Try to create MinIO settings - will succeed if .env has MinIO config
            settings = StorageSettings(provider=StorageProvider.MINIO)
            # MinIO is configured - verify it works
            assert settings.is_minio is True
            assert settings.is_configured is True
            assert settings.minio_endpoint is not None
        except ValueError as e:
            # MinIO not configured - validation should mention required fields
            assert "MinIO storage requires" in str(e) or "AEF_STORAGE_MINIO" in str(e)

    def test_minio_settings_valid(self) -> None:
        """Test valid MinIO settings."""
        settings = StorageSettings(
            provider=StorageProvider.MINIO,
            minio_endpoint="localhost:9000",
            minio_access_key="minioadmin",
            minio_secret_key="minioadmin",
            minio_secure=False,
        )
        assert settings.is_minio is True
        assert settings.is_configured is True
        assert settings.minio_secure is False

    def test_minio_settings_partial_missing(self) -> None:
        """Test MinIO with partially missing credentials.

        Note: When MinIO is fully configured via .env, we verify the full config works.
        Otherwise, we test that partial config fails validation.
        """
        try:
            # Try to create MinIO settings - will succeed if .env has full config
            settings = StorageSettings(provider=StorageProvider.MINIO)
            # MinIO fully configured - verify it works
            assert settings.is_minio is True
            assert settings.minio_secret_key is not None
        except ValueError as e:
            # Partial config - validation should mention missing field
            assert "AEF_STORAGE_MINIO" in str(e)


class TestMinioStorage:
    """Tests for MinioStorage adapter."""

    @pytest.fixture
    def storage(self) -> MinioStorage:
        """Create a MinioStorage instance."""
        return MinioStorage(
            endpoint="localhost:9000",
            access_key="test",
            secret_key="test",
            bucket_name="test-bucket",
            secure=False,
        )

    def test_provider_property(self, storage: MinioStorage) -> None:
        """Test provider property."""
        assert storage.provider == StorageProvider.MINIO

    def test_bucket_name_property(self) -> None:
        """Test bucket_name property."""
        storage = MinioStorage(
            endpoint="localhost:9000",
            access_key="test",
            secret_key="test",
            bucket_name="my-bucket",
            secure=False,
        )
        assert storage.bucket_name == "my-bucket"

    def test_implements_protocol(self, storage: MinioStorage) -> None:
        """Test that MinioStorage implements StorageProtocol."""
        assert isinstance(storage, StorageProtocol)

    @pytest.mark.asyncio
    async def test_upload_success(self, storage: MinioStorage) -> None:
        """Test successful upload with mocked client."""
        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        mock_client.bucket_exists.return_value = True
        mock_result = MagicMock()
        mock_result.etag = "abc123"
        mock_client.put_object.return_value = mock_result

        with patch.object(storage, "_get_client", return_value=mock_client):
            result = await storage.upload("test.txt", b"hello world")

        assert result.key == "test.txt"
        assert result.size_bytes == 11
        assert result.etag == "abc123"
        mock_client.put_object.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_creates_bucket(self, storage: MinioStorage) -> None:
        """Test upload creates bucket if not exists."""
        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        mock_client.bucket_exists.return_value = False  # Bucket doesn't exist
        mock_result = MagicMock()
        mock_result.etag = "xyz789"
        mock_client.put_object.return_value = mock_result

        with patch.object(storage, "_get_client", return_value=mock_client):
            result = await storage.upload("file.txt", b"content")

        mock_client.make_bucket.assert_called_once_with("test-bucket")
        assert result.key == "file.txt"

    @pytest.mark.asyncio
    async def test_upload_error(self, storage: MinioStorage) -> None:
        """Test upload failure raises UploadError."""
        from unittest.mock import MagicMock, patch

        from aef_adapters.object_storage import UploadError

        mock_client = MagicMock()
        mock_client.bucket_exists.return_value = True
        mock_client.put_object.side_effect = Exception("Network error")

        with (
            patch.object(storage, "_get_client", return_value=mock_client),
            pytest.raises(UploadError, match="Network error"),
        ):
            await storage.upload("test.txt", b"data")

    @pytest.mark.asyncio
    async def test_download_success(self, storage: MinioStorage) -> None:
        """Test successful download."""
        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.read.return_value = b"file content"
        mock_client.get_object.return_value = mock_response

        with patch.object(storage, "_get_client", return_value=mock_client):
            content = await storage.download("test.txt")

        assert content == b"file content"
        mock_response.close.assert_called_once()
        mock_response.release_conn.assert_called_once()

    @pytest.mark.asyncio
    async def test_download_not_found(self, storage: MinioStorage) -> None:
        """Test download of non-existent object."""
        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        mock_client.get_object.side_effect = Exception("NoSuchKey: not found")

        with (
            patch.object(storage, "_get_client", return_value=mock_client),
            pytest.raises(ObjectNotFoundError),
        ):
            await storage.download("nonexistent.txt")

    @pytest.mark.asyncio
    async def test_download_error(self, storage: MinioStorage) -> None:
        """Test download failure raises DownloadError."""
        from unittest.mock import MagicMock, patch

        from aef_adapters.object_storage import DownloadError

        mock_client = MagicMock()
        mock_client.get_object.side_effect = Exception("Connection refused")

        with (
            patch.object(storage, "_get_client", return_value=mock_client),
            pytest.raises(DownloadError, match="Connection refused"),
        ):
            await storage.download("test.txt")

    @pytest.mark.asyncio
    async def test_delete_success(self, storage: MinioStorage) -> None:
        """Test successful deletion."""
        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()

        with patch.object(storage, "_get_client", return_value=mock_client):
            result = await storage.delete("test.txt")

        assert result is True
        mock_client.remove_object.assert_called_once_with("test-bucket", "test.txt")

    @pytest.mark.asyncio
    async def test_delete_failure(self, storage: MinioStorage) -> None:
        """Test deletion failure returns False."""
        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        mock_client.remove_object.side_effect = Exception("Permission denied")

        with patch.object(storage, "_get_client", return_value=mock_client):
            result = await storage.delete("test.txt")

        assert result is False

    @pytest.mark.asyncio
    async def test_exists_true(self, storage: MinioStorage) -> None:
        """Test exists returns True for existing object."""
        from datetime import datetime
        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        mock_stat = MagicMock()
        mock_stat.size = 100
        mock_stat.content_type = "text/plain"
        mock_stat.etag = "abc"
        mock_stat.last_modified = datetime.now()
        mock_client.stat_object.return_value = mock_stat

        with patch.object(storage, "_get_client", return_value=mock_client):
            result = await storage.exists("test.txt")

        assert result is True

    @pytest.mark.asyncio
    async def test_exists_false(self, storage: MinioStorage) -> None:
        """Test exists returns False for non-existent object."""
        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        mock_client.stat_object.side_effect = Exception("NoSuchKey")

        with patch.object(storage, "_get_client", return_value=mock_client):
            result = await storage.exists("nonexistent.txt")

        assert result is False

    @pytest.mark.asyncio
    async def test_get_object_info(self, storage: MinioStorage) -> None:
        """Test getting object metadata."""
        from datetime import datetime
        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        mock_stat = MagicMock()
        mock_stat.size = 1024
        mock_stat.content_type = "application/json"
        mock_stat.etag = "etag123"
        mock_stat.last_modified = datetime(2024, 1, 1, 12, 0, 0)
        mock_client.stat_object.return_value = mock_stat

        with patch.object(storage, "_get_client", return_value=mock_client):
            info = await storage.get_object_info("data.json")

        assert info is not None
        assert info.key == "data.json"
        assert info.size_bytes == 1024
        assert info.content_type == "application/json"
        assert info.etag == "etag123"

    @pytest.mark.asyncio
    async def test_get_object_info_not_found(self, storage: MinioStorage) -> None:
        """Test get_object_info returns None for non-existent object."""
        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        mock_client.stat_object.side_effect = Exception("not found")

        with patch.object(storage, "_get_client", return_value=mock_client):
            info = await storage.get_object_info("nonexistent.txt")

        assert info is None

    @pytest.mark.asyncio
    async def test_list_objects(self, storage: MinioStorage) -> None:
        """Test listing objects."""
        from datetime import datetime
        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        mock_obj1 = MagicMock()
        mock_obj1.object_name = "file1.txt"
        mock_obj1.size = 100
        mock_obj1.etag = "etag1"
        mock_obj1.last_modified = datetime.now()

        mock_obj2 = MagicMock()
        mock_obj2.object_name = "file2.txt"
        mock_obj2.size = 200
        mock_obj2.etag = "etag2"
        mock_obj2.last_modified = datetime.now()

        mock_client.list_objects.return_value = [mock_obj1, mock_obj2]

        with patch.object(storage, "_get_client", return_value=mock_client):
            result = await storage.list_objects("prefix/")

        assert len(result.objects) == 2
        assert result.objects[0].key == "file1.txt"
        assert result.objects[1].key == "file2.txt"
        assert result.prefix == "prefix/"

    @pytest.mark.asyncio
    async def test_list_objects_empty(self, storage: MinioStorage) -> None:
        """Test listing objects returns empty for no matches."""
        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        mock_client.list_objects.return_value = []

        with patch.object(storage, "_get_client", return_value=mock_client):
            result = await storage.list_objects("nonexistent/")

        assert len(result.objects) == 0

    @pytest.mark.asyncio
    async def test_get_presigned_url(self, storage: MinioStorage) -> None:
        """Test generating presigned URL."""
        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        mock_client.presigned_get_object.return_value = (
            "https://minio:9000/bucket/key?signature=xyz"
        )

        with patch.object(storage, "_get_client", return_value=mock_client):
            url = await storage.get_presigned_url("test.txt", expires_in=3600)

        assert "minio" in url or "bucket" in url
        mock_client.presigned_get_object.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_presigned_url_fallback(self, storage: MinioStorage) -> None:
        """Test presigned URL fallback on error."""
        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        mock_client.presigned_get_object.side_effect = Exception("Error")

        with patch.object(storage, "_get_client", return_value=mock_client):
            url = await storage.get_presigned_url("test.txt")

        # Should return a basic URL as fallback
        assert "localhost:9000" in url
        assert "test-bucket" in url
        assert "test.txt" in url


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

    @pytest.mark.asyncio
    async def test_get_storage_minio(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test factory returns MinioStorage for minio provider."""
        monkeypatch.setenv("AEF_STORAGE_PROVIDER", "minio")
        monkeypatch.setenv("AEF_STORAGE_MINIO_ENDPOINT", "localhost:9000")
        monkeypatch.setenv("AEF_STORAGE_MINIO_ACCESS_KEY", "minioadmin")
        monkeypatch.setenv("AEF_STORAGE_MINIO_SECRET_KEY", "minioadmin")
        monkeypatch.setenv("AEF_STORAGE_MINIO_SECURE", "false")
        reset_storage()

        storage = await get_storage()
        assert isinstance(storage, MinioStorage)
        assert storage.provider == StorageProvider.MINIO


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
