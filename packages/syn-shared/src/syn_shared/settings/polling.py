"""Polling settings for GitHub Events API hybrid ingestion (ISS-386)."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PollingSettings(BaseSettings):
    """Configuration for GitHub Events API polling.

    Polling is **enabled by default** (zero-config onboarding). Set
    ``SYN_POLLING_DISABLED=true`` to opt out when using webhooks exclusively.
    """

    model_config = SettingsConfigDict(
        env_prefix="SYN_POLLING_",
        env_file=".env",
        extra="ignore",
    )

    disabled: bool = Field(
        default=False,
        description=(
            "Disable GitHub Events API polling. "
            "Polling is ON by default for zero-config onboarding. "
            "Set to true if using webhooks exclusively."
        ),
    )

    poll_interval_seconds: float = Field(
        default=60.0,
        ge=10.0,
        description="Base polling interval in ACTIVE_POLLING mode (seconds).",
    )

    safety_net_interval_seconds: float = Field(
        default=300.0,
        ge=60.0,
        description="Polling interval in SAFETY_NET mode when webhooks are healthy (seconds).",
    )

    webhook_stale_threshold_seconds: float = Field(
        default=1800.0,
        ge=60.0,
        description="Seconds without webhook delivery before switching to ACTIVE_POLLING.",
    )

    dedup_ttl_seconds: int = Field(
        default=86400,
        ge=3600,
        description="TTL for dedup keys in Redis (seconds).",
    )

    # -- Check-run polling (poll-based self-healing, #602) -------------------

    check_run_poll_interval_seconds: float = Field(
        default=30.0,
        ge=10.0,
        description=(
            "Check-run polling interval when webhooks are stale (seconds). "
            "Controls how quickly CI failures are detected without webhooks."
        ),
    )

    check_run_safety_interval_seconds: float = Field(
        default=120.0,
        ge=30.0,
        description=(
            "Check-run polling interval when webhooks are healthy (seconds). "
            "Relaxed cadence since webhooks provide real-time check_run events."
        ),
    )

    check_run_sha_ttl_seconds: int = Field(
        default=7200,
        description="Max age for pending SHAs before cleanup (seconds). Default 2h.",
    )

    @property
    def enabled(self) -> bool:
        """Whether polling is enabled (inverse of ``disabled``)."""
        return not self.disabled
