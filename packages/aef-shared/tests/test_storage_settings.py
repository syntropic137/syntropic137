"""Tests for StorageSettings."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from aef_shared.settings.storage import StorageProvider, StorageSettings


class TestStorageSettings:
    """Tests for StorageSettings configuration."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        settings = StorageSettings()

        assert settings.provider == StorageProvider.LOCAL
        assert settings.local_path == Path(".artifacts")
        assert settings.bucket_name == "aef-artifacts"
        assert settings.max_file_size_mb == 50
        assert settings.presigned_url_expiry_seconds == 3600

    def test_local_provider_is_configured(self) -> None:
        """Test that local provider is always configured."""
        settings = StorageSettings(provider=StorageProvider.LOCAL)

        assert settings.is_local is True
        assert settings.is_supabase is False
        assert settings.is_configured is True

    def test_supabase_provider_requires_credentials(self) -> None:
        """Test that Supabase provider requires URL and key."""
        with pytest.raises(ValueError) as exc_info:
            StorageSettings(provider=StorageProvider.SUPABASE)

        error_msg = str(exc_info.value)
        assert "AEF_STORAGE_SUPABASE_URL" in error_msg
        assert "AEF_STORAGE_SUPABASE_KEY" in error_msg

    def test_supabase_provider_requires_url(self) -> None:
        """Test that Supabase provider requires URL."""
        with pytest.raises(ValueError) as exc_info:
            StorageSettings(
                provider=StorageProvider.SUPABASE,
                supabase_key=SecretStr("secret-key"),
            )

        assert "AEF_STORAGE_SUPABASE_URL" in str(exc_info.value)

    def test_supabase_provider_requires_key(self) -> None:
        """Test that Supabase provider requires key."""
        with pytest.raises(ValueError) as exc_info:
            StorageSettings(
                provider=StorageProvider.SUPABASE,
                supabase_url="https://example.supabase.co",
            )

        assert "AEF_STORAGE_SUPABASE_KEY" in str(exc_info.value)

    def test_supabase_provider_valid_config(self) -> None:
        """Test valid Supabase configuration."""
        settings = StorageSettings(
            provider=StorageProvider.SUPABASE,
            supabase_url="https://example.supabase.co",
            supabase_key=SecretStr("secret-key"),
            bucket_name="my-bucket",
        )

        assert settings.is_supabase is True
        assert settings.is_local is False
        assert settings.is_configured is True
        assert settings.bucket_name == "my-bucket"

    def test_max_file_size_bytes_conversion(self) -> None:
        """Test max file size conversion from MB to bytes."""
        settings = StorageSettings(max_file_size_mb=100)
        assert settings.max_file_size_bytes == 100 * 1024 * 1024

        settings = StorageSettings(max_file_size_mb=1)
        assert settings.max_file_size_bytes == 1024 * 1024

    def test_from_environment_variables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test loading settings from environment variables."""
        monkeypatch.setenv("AEF_STORAGE_PROVIDER", "local")
        monkeypatch.setenv("AEF_STORAGE_LOCAL_PATH", "/tmp/test-artifacts")
        monkeypatch.setenv("AEF_STORAGE_MAX_FILE_SIZE_MB", "25")

        settings = StorageSettings()

        assert settings.provider == StorageProvider.LOCAL
        assert settings.local_path == Path("/tmp/test-artifacts")
        assert settings.max_file_size_mb == 25

    def test_supabase_from_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test loading Supabase settings from environment."""
        monkeypatch.setenv("AEF_STORAGE_PROVIDER", "supabase")
        monkeypatch.setenv("AEF_STORAGE_SUPABASE_URL", "https://test.supabase.co")
        monkeypatch.setenv("AEF_STORAGE_SUPABASE_KEY", "test-key")
        monkeypatch.setenv("AEF_STORAGE_BUCKET_NAME", "test-bucket")

        settings = StorageSettings()

        assert settings.is_supabase is True
        assert settings.supabase_url == "https://test.supabase.co"
        assert settings.supabase_key.get_secret_value() == "test-key"
        assert settings.bucket_name == "test-bucket"


class TestStorageProvider:
    """Tests for StorageProvider enum."""

    def test_provider_values(self) -> None:
        """Test provider enum values."""
        assert StorageProvider.LOCAL.value == "local"
        assert StorageProvider.SUPABASE.value == "supabase"

    def test_provider_from_string(self) -> None:
        """Test creating provider from string."""
        assert StorageProvider("local") == StorageProvider.LOCAL
        assert StorageProvider("supabase") == StorageProvider.SUPABASE
