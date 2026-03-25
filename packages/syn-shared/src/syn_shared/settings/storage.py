"""Object storage settings for artifact storage.

This module provides configuration for object storage backends.
Used to store and retrieve agent artifacts like outputs, reports, and files.

Environment Variables:
    SYN_STORAGE_* - Object storage configuration

Usage:
    from syn_shared.settings import get_settings

    settings = get_settings()
    storage = settings.storage
    provider = storage.provider  # "local" | "supabase" | "minio"
"""

from __future__ import annotations

import logging
import os
from enum import Enum
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_logger = logging.getLogger(__name__)


class StorageProvider(str, Enum):
    """Available storage providers for artifacts.

    LOCAL: Filesystem storage (development/testing)
    SUPABASE: Supabase Storage (S3-compatible, production)
    MINIO: MinIO Storage (S3-compatible, self-hosted)
    """

    LOCAL = "local"
    SUPABASE = "supabase"
    MINIO = "minio"


class StorageSettings(BaseSettings):
    """Object storage configuration for artifacts.

    Controls where agent artifacts are stored (outputs, reports, files).
    Supports local filesystem, Supabase Storage, and MinIO.

    Override via SYN_STORAGE_* environment variables.

    Example:
        # Local development (filesystem)
        SYN_STORAGE_PROVIDER=local
        SYN_STORAGE_LOCAL_PATH=.artifacts

        # MinIO (local dev with S3 API - default for `just dev`)
        SYN_STORAGE_PROVIDER=minio
        SYN_STORAGE_MINIO_ENDPOINT=localhost:9000
        SYN_STORAGE_MINIO_ACCESS_KEY=minioadmin
        SYN_STORAGE_MINIO_SECRET_KEY=minioadmin
        SYN_STORAGE_MINIO_SECURE=false

        # Supabase (production)
        SYN_STORAGE_PROVIDER=supabase
        SYN_STORAGE_SUPABASE_URL=https://xxx.supabase.co
        SYN_STORAGE_SUPABASE_KEY=eyJ...
        SYN_STORAGE_BUCKET_NAME=syn-artifacts
    """

    model_config = SettingsConfigDict(
        env_prefix="SYN_STORAGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # =========================================================================
    # PROVIDER SELECTION
    # =========================================================================

    provider: StorageProvider = Field(
        default=StorageProvider.LOCAL,
        description=(
            "Storage provider to use. "
            "Options: 'local' (filesystem), 'supabase' (S3-compatible). "
            "Default: local (development). Use supabase for production."
        ),
    )

    # =========================================================================
    # LOCAL STORAGE SETTINGS
    # =========================================================================

    local_path: Path = Field(
        default=Path(".artifacts"),
        description=(
            "Directory path for local file storage. "
            "Relative paths are resolved from the workspace root. "
            "Default: .artifacts"
        ),
    )

    # =========================================================================
    # SUPABASE STORAGE SETTINGS
    # =========================================================================

    supabase_url: str = Field(
        default="",
        description=(
            "Supabase project URL. "
            "Format: https://<project-ref>.supabase.co "
            "Required when provider is 'supabase'. "
            "Get from: Supabase Dashboard > Settings > API"
        ),
    )

    supabase_key: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "Supabase service role key (for server-side access). "
            "Use service_role key, NOT anon key, for storage operations. "
            "Required when provider is 'supabase'. "
            "Get from: Supabase Dashboard > Settings > API > service_role"
        ),
    )

    bucket_name: str = Field(
        default="syn-artifacts",
        description=(
            "Storage bucket name for artifacts. "
            "Used by Supabase and MinIO providers. "
            "Default: syn-artifacts"
        ),
    )

    # =========================================================================
    # MINIO STORAGE SETTINGS
    # =========================================================================

    minio_endpoint: str = Field(
        default="",
        description=(
            "MinIO server endpoint (host:port). "
            "Example: 'localhost:9000' or 'minio.example.com:9000'. "
            "Required when provider is 'minio'."
        ),
    )

    minio_access_key: str = Field(
        default="",
        description=("MinIO access key (username). Required when provider is 'minio'."),
    )

    minio_secret_key: SecretStr = Field(
        default=SecretStr(""),
        description=("MinIO secret key (password). Required when provider is 'minio'."),
    )

    minio_secure: bool = Field(
        default=False,
        description=(
            "Use HTTPS for MinIO connections. "
            "Default: false (Docker-internal networking uses plain HTTP). "
            "Set to true for external deployments with TLS."
        ),
    )

    # =========================================================================
    # OPTIONAL SETTINGS
    # =========================================================================

    max_file_size_mb: int = Field(
        default=50,
        ge=1,
        le=500,
        description=(
            "Maximum file size in MB for artifact uploads. "
            "Larger files will be rejected. Default: 50MB."
        ),
    )

    presigned_url_expiry_seconds: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description=(
            "Expiry time for presigned URLs in seconds. "
            "Default: 3600 (1 hour). Max: 86400 (24 hours)."
        ),
    )

    # =========================================================================
    # COMPUTED PROPERTIES
    # =========================================================================

    @property
    def max_file_size_bytes(self) -> int:
        """Get max file size in bytes."""
        return self.max_file_size_mb * 1024 * 1024

    @property
    def is_local(self) -> bool:
        """Check if using local filesystem storage."""
        return self.provider == StorageProvider.LOCAL

    @property
    def is_supabase(self) -> bool:
        """Check if using Supabase storage."""
        return self.provider == StorageProvider.SUPABASE

    @property
    def is_minio(self) -> bool:
        """Check if using MinIO storage."""
        return self.provider == StorageProvider.MINIO

    @property
    def is_configured(self) -> bool:
        """Check if storage is properly configured.

        Returns True if:
        - Local provider: always configured
        - Supabase provider: URL and key are set
        - MinIO provider: endpoint, access key, and secret key are set
        """
        if self.is_local:
            return True
        if self.is_supabase:
            return bool(self.supabase_url and self.supabase_key.get_secret_value())
        if self.is_minio:
            return bool(
                self.minio_endpoint
                and self.minio_access_key
                and self.minio_secret_key.get_secret_value()
            )
        return False

    # =========================================================================
    # VALIDATION
    # =========================================================================

    @model_validator(mode="after")
    def warn_local_provider_in_production(self) -> StorageSettings:
        """Warn if using LOCAL storage outside test/offline mode."""
        if self.provider == StorageProvider.LOCAL:
            app_env = os.environ.get("APP_ENVIRONMENT", "development").lower()
            if app_env not in ("test", "offline"):
                _logger.warning(
                    "SYN_STORAGE_PROVIDER=local — artifact storage uses filesystem. "
                    "Set SYN_STORAGE_PROVIDER=minio for Docker/selfhost deployments."
                )
        return self

    @staticmethod
    def _check_required_fields(
        provider_name: str,
        fields: dict[str, str | SecretStr],
        env_names: dict[str, str],
    ) -> None:
        """Raise ``ValueError`` if any required field is empty."""
        missing = [
            env_names[name]
            for name, value in fields.items()
            if not (value.get_secret_value() if isinstance(value, SecretStr) else value)
        ]
        if missing:
            msg = (
                f"{provider_name} storage requires: {', '.join(missing)}. "
                "Set these environment variables or use provider='local'."
            )
            raise ValueError(msg)

    @model_validator(mode="after")
    def validate_provider_config(self) -> StorageSettings:
        """Ensure provider-specific settings are complete."""
        if self.provider == StorageProvider.SUPABASE:
            self._check_required_fields(
                "Supabase",
                {"supabase_url": self.supabase_url, "supabase_key": self.supabase_key},
                {
                    "supabase_url": "SYN_STORAGE_SUPABASE_URL",
                    "supabase_key": "SYN_STORAGE_SUPABASE_KEY",
                },
            )
        elif self.provider == StorageProvider.MINIO:
            self._check_required_fields(
                "MinIO",
                {
                    "minio_endpoint": self.minio_endpoint,
                    "minio_access_key": self.minio_access_key,
                    "minio_secret_key": self.minio_secret_key,
                },
                {
                    "minio_endpoint": "SYN_STORAGE_MINIO_ENDPOINT",
                    "minio_access_key": "SYN_STORAGE_MINIO_ACCESS_KEY",
                    "minio_secret_key": "SYN_STORAGE_MINIO_SECRET_KEY",
                },
            )
        return self
