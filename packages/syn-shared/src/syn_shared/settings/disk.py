"""Disk-space thresholds for the workspace volume (#1560).

Workspace directories are the largest thing this platform writes to the host,
and they share a filesystem with Postgres on a single-host deployment. Running
that filesystem out of space did not fail cleanly: an execution got as far as a
Postgres write and died there with ENOSPC. These two numbers turn "the disk is
full" into something /health says early and admission refuses up front.
"""

from __future__ import annotations

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DiskSettings(BaseSettings):
    """When free space on the workspace volume becomes a degraded or refused state."""

    model_config = SettingsConfigDict(
        env_prefix="SYN_DISK_",
        env_file=".env",
        extra="ignore",
    )

    path: str = Field(
        default="",
        description=(
            "Directory whose filesystem is measured. Empty means the workspace "
            "directory (SYN_WORKSPACE_CONTAINER_DIR, default /workspaces), which is "
            "the volume workspace directories fill."
        ),
    )

    degraded_below_percent: float = Field(
        # 15, not 10 (PC-130): at 10 the page came with too little room left
        # to reclaim by hand before admission closed at 5.
        default=15.0,
        gt=0.0,
        lt=100.0,
        description="/health reports mode=degraded (reason disk_space) below this percent free.",
    )

    refuse_admission_below_percent: float = Field(
        default=5.0,
        gt=0.0,
        lt=100.0,
        description=(
            "New executions are refused (HTTP 507) below this percent free, rather "
            "than admitted to fail mid-write when Postgres runs out of space."
        ),
    )

    reclaim_grace_hours: float = Field(
        default=6.0,
        gt=0.0,
        description=(
            "A workspace directory with no container and no running execution is "
            "reclaimed only once nothing in it has changed for this many hours (PC-130)."
        ),
    )

    reclaim_interval_minutes: float = Field(
        default=30.0,
        gt=0.0,
        description="How often stale workspace directories are looked for (PC-130).",
    )

    @model_validator(mode="after")
    def _floor_below_threshold(self) -> DiskSettings:
        # A floor above the warning threshold would refuse work while /health
        # still said the disk was fine, which is the silent refusal this
        # setting exists to replace.
        if self.refuse_admission_below_percent > self.degraded_below_percent:
            raise ValueError(
                "SYN_DISK_REFUSE_ADMISSION_BELOW_PERCENT must not exceed "
                "SYN_DISK_DEGRADED_BELOW_PERCENT"
            )
        return self
