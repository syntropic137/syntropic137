"""Tests for StorageSettings."""

from __future__ import annotations

from pathlib import Path

import pytest

from syn_shared.settings.storage import StorageProvider, StorageSettings


@pytest.mark.integration
class TestStorageSettings:
    """Tests for StorageSettings configuration."""

    def test_default_values(self) -> None:
        """Test default configuration values when explicitly set to local.

        Note: We test explicit local provider since .env may configure different defaults.
        """
        settings = StorageSettings(provider=StorageProvider.LOCAL)

        assert settings.provider == StorageProvider.LOCAL
        assert settings.local_path == Path(".artifacts")
        assert settings.bucket_name == "syn-artifacts"
        assert settings.max_file_size_mb == 50
        assert settings.presigned_url_expiry_seconds == 3600

    def test_local_provider_is_configured(self) -> None:
        """Test that local provider is always configured."""
        settings = StorageSettings(provider=StorageProvider.LOCAL)

        assert settings.is_local is True
        assert settings.is_configured is True

    def test_max_file_size_bytes_conversion(self) -> None:
        """Test max file size conversion from MB to bytes."""
        settings = StorageSettings(max_file_size_mb=100)
        assert settings.max_file_size_bytes == 100 * 1024 * 1024

        settings = StorageSettings(max_file_size_mb=1)
        assert settings.max_file_size_bytes == 1024 * 1024

    def test_from_environment_variables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test loading settings from environment variables."""
        monkeypatch.setenv("SYN_STORAGE_PROVIDER", "local")
        monkeypatch.setenv("SYN_STORAGE_LOCAL_PATH", "/tmp/test-artifacts")
        monkeypatch.setenv("SYN_STORAGE_MAX_FILE_SIZE_MB", "25")

        settings = StorageSettings()

        assert settings.provider == StorageProvider.LOCAL
        assert settings.local_path == Path("/tmp/test-artifacts")
        assert settings.max_file_size_mb == 25


class TestStorageProvider:
    """Tests for StorageProvider enum."""

    def test_provider_values(self) -> None:
        """Test provider enum values."""
        assert StorageProvider.LOCAL.value == "local"
        assert StorageProvider.MINIO.value == "minio"

    def test_provider_from_string(self) -> None:
        """Test creating provider from string."""
        assert StorageProvider("local") == StorageProvider.LOCAL
        assert StorageProvider("minio") == StorageProvider.MINIO
