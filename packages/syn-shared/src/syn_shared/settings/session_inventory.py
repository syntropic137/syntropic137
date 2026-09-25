"""Local session inventory configuration. SeshMagic is an optional replica."""

from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SessionInventorySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SYN_SESSION_INVENTORY_",
        env_file=".env",
        extra="ignore",
        hide_input_in_errors=True,
        env_ignore_empty=True,
        frozen=True,
    )

    archive_dir: Path = Field(
        default_factory=lambda: Path.home() / ".syntropic137" / "session-inventory",
        description="Absolute host-owned durable directory for native transcript bytes and installation identity. Mount a persistent volume in containers.",
    )
    source_instance_id: str = Field(
        default="",
        max_length=128,
        description="Stable unique installation identity. Empty uses an identity persisted in the archive directory. Never reuse across independent installations.",
    )
    sweep_interval_seconds: int = Field(
        default=30,
        ge=1,
        le=3600,
        description="Interval between durable inventory recovery signals.",
    )
    settlement_grace_seconds: int = Field(
        default=1800,
        ge=0,
        le=604800,
        description="Bounded wait after an execution ends for its descendants and captures to settle. After it, anything still unsettled becomes an explicit coverage gap instead of holding coverage open forever.",
    )
    lease_seconds: int = Field(
        default=120,
        ge=30,
        le=3600,
        description="Worker lease, renewed between bounded evidence and publication batches.",
    )
    retry_seconds: int = Field(
        default=10,
        ge=1,
        le=3600,
        description="Delay before retrying an interrupted inventory step.",
    )
    max_jobs_per_tick: int = Field(
        default=2,
        ge=1,
        le=50,
        description="Maximum inventory steps dispatched per live recovery signal.",
    )
    max_evidence_records: int = Field(
        default=100000,
        ge=1,
        description="Per-reconstruction record quota. Exceeding it fails the job and preserves the previous inventory.",
    )
    max_evidence_batches: int = Field(
        default=10000,
        ge=1,
        description="Per-reconstruction journal batch quota. Exceeding it never publishes a truncated result.",
    )

    local_body_retention_seconds: int | None = Field(
        default=None,
        ge=1,
        description="Optional local body lifetime since first catalog acquisition. Disabled by default. Expiry permanently deletes exact shared bytes but retains discovery history. When capture replication is enabled, deletion propagates asynchronously to that destination.",
    )

    replication_enabled: bool = Field(
        default=False,
        description="Enable optional workflow inventory replication through the standard exporter.",
    )
    replication_store_url: str | None = Field(
        default=None,
        description="Optional inventory replica base URL. Required when replication is enabled; no credentials or query string.",
    )
    replication_write_token: SecretStr | None = Field(
        default=None,
        description="Namespace-scoped inventory write token, separate from ordinary transcript upload credentials.",
    )
    capture_replication_enabled: bool = Field(
        default=False,
        description="Deliver archived envelopes through the standard exporter alongside inventory replication.",
    )
    capture_write_token: SecretStr | None = Field(
        default=None,
        description="Explicit source-scoped capture credential, independent of inventory authority.",
    )
    exporter_binary: Path = Field(
        default=Path("/usr/local/bin/apss-session-exporter"),
        description="Absolute path to the released standard exporter used for inventory replication.",
    )

    @field_validator("exporter_binary")
    @classmethod
    def _absolute_exporter(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("inventory exporter binary must be absolute")
        return value

    @model_validator(mode="after")
    def _capture_configuration(self) -> "SessionInventorySettings":
        if not self.capture_replication_enabled:
            return self
        if not self.replication_enabled or self.capture_write_token is None:
            raise ValueError("capture delivery requires replication enabled and a capture token")
        capture_token = self.capture_write_token.get_secret_value()
        if (
            not capture_token
            or len(capture_token) > 4096
            or any(not 33 <= ord(char) <= 126 for char in capture_token)
        ):
            raise ValueError("capture token must be a nonblank bearer credential")
        return self

    @model_validator(mode="after")
    def _replication_configuration(self) -> "SessionInventorySettings":
        if not self.replication_enabled:
            return self
        if self.replication_store_url is None or self.replication_write_token is None:
            raise ValueError("enabled inventory replication requires a URL and namespace token")
        self._validate_replica_url(self.replication_store_url)
        token = self.replication_write_token.get_secret_value()
        if not token.strip() or any(ord(char) < 32 or ord(char) > 126 for char in token):
            raise ValueError("inventory namespace token must be a nonblank HTTP header value")
        return self

    @staticmethod
    def _validate_replica_url(value: str) -> None:
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "inventory replica URL must be HTTP(S) without credentials, query, or fragment"
            )

    @field_validator("archive_dir")
    @classmethod
    def _absolute_archive(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("session inventory archive directory must be absolute")
        return value

    @field_validator("source_instance_id")
    @classmethod
    def _valid_identity(cls, value: str) -> str:
        if value and (not value.strip() or "\x00" in value):
            raise ValueError("source identity must be nonblank and contain no NUL")
        value.encode("utf-8")
        return value
