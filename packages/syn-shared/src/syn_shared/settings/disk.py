"""Disk-space thresholds for the workspace volume (#1560, #1947).

Workspace directories are the largest thing this platform writes to the host,
and they share a filesystem with Postgres on a single-host deployment. Running
that filesystem out of space did not fail cleanly: an execution got as far as a
Postgres write and died there with ENOSPC. These numbers turn "the disk is
full" into something /health says early and admission refuses up front.

The floors are absolute GiB (#1947). A run needs a number of bytes, not a share
of the disk: 3.9% free of a 2 TB disk is 71 GiB, room for many runs, while 6%
of a 100 GB disk is 6 GiB. The default admission floor is one run reserve per
execution that can be in flight (`SYN_EXECUTION_MAX_CONCURRENT`), so it grows
with concurrency instead of being re-tuned by hand at 20, 100 and 1,000.
"""

from __future__ import annotations

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Disk one running execution may need, in GiB. The upper end of the 1-3 GB
#: per phase in docs/north-star.md (clone, dependencies, caches; most phases
#: start cold). Cross-checked 2026-10-14 (#1947): a checkout of this repository
#: with submodules and `uv sync` + `pnpm install` done is 1.5 GiB, and its cold
#: uv/pnpm caches add 1-2 GiB (see SYN_DEPENDENCY_SEED_MAX_BYTES). Measured disk
#: at teardown (`workspace_resource_usage`) had n=0 on the live deployment, so
#: this is not yet a percentile. A running execution holds one workspace at a
#: time, so this is per in-flight run, not per phase summed. The workspace image
#: (4 GB for the claude image) is shared by every run on the host and is not in it.
DEFAULT_RUN_RESERVE_GIB = 3.0

#: The degraded floor, as a multiple of the admission floor when not set: one
#: more full set of in-flight runs, so the page comes with room to reclaim by
#: hand (PC-130) and to pull a new workspace image at the next upgrade.
DEGRADED_FLOOR_MULTIPLE = 2.0


class DiskSettings(BaseSettings):
    """When free space on the workspace volume becomes a degraded or refused state."""

    model_config = SettingsConfigDict(
        env_prefix="SYN_DISK_",
        env_file=".env",
        extra="ignore",
        # `SYN_DISK_REFUSE_ADMISSION_BELOW_GIB=` copied from .env.example means
        # "use the derived default", not "parse '' as a number".
        env_ignore_empty=True,
    )

    path: str = Field(
        default="",
        description=(
            "Directory whose filesystem is measured. Empty means the workspace "
            "directory (SYN_WORKSPACE_CONTAINER_DIR, default /workspaces), which is "
            "the volume workspace directories fill."
        ),
    )

    run_reserve_gib: float = Field(
        default=DEFAULT_RUN_RESERVE_GIB,
        gt=0.0,
        description=(
            "Disk one running execution may still write: its workspace directory "
            "(clone, dependencies, caches) and its capture. The default admission "
            "floor is this times SYN_EXECUTION_MAX_CONCURRENT, so every run that "
            "can be in flight has room to finish."
        ),
    )

    refuse_admission_below_gib: float | None = Field(
        default=None,
        gt=0.0,
        description=(
            "New executions are refused (HTTP 507) below this many GiB free. Empty "
            "means SYN_DISK_RUN_RESERVE_GIB x SYN_EXECUTION_MAX_CONCURRENT (12 GiB "
            "at the defaults). Absolute, so a large disk with a small percent free "
            "still admits work."
        ),
    )

    degraded_below_gib: float | None = Field(
        default=None,
        gt=0.0,
        description=(
            "/health reports mode=degraded (reason disk_space) below this many GiB "
            "free. Empty means twice the admission floor (24 GiB at the defaults): "
            "room to reclaim by hand before admission closes. Never below the "
            "admission floor."
        ),
    )

    degraded_below_percent: float | None = Field(
        default=None,
        gt=0.0,
        lt=100.0,
        description=(
            "Optional. Also degrade /health below this percent free. Empty (the "
            "default) judges on GiB alone: a percent of a 2 TB disk is far more "
            "than any run needs."
        ),
    )

    refuse_admission_below_percent: float | None = Field(
        default=None,
        gt=0.0,
        lt=100.0,
        description=(
            "Optional. Also refuse new executions below this percent free. Empty "
            "(the default) judges on GiB alone. When set, crossing either floor "
            "refuses."
        ),
    )

    reclaim_settle_minutes: float = Field(
        default=10.0,
        ge=0.0,
        description=(
            "A workspace directory is reclaimed only once its owning execution has "
            "been terminal (completed, failed or cancelled) for this many minutes, "
            "measured from the terminal event, never from file times (#1983)."
        ),
    )

    reclaim_interval_minutes: float = Field(
        default=30.0,
        gt=0.0,
        description=(
            "How often stale workspace directories are looked for (PC-130). Free "
            "space falling to low or critical also starts a pass at once (#1983)."
        ),
    )

    reclaim_pass_budget_minutes: float = Field(
        default=5.0,
        gt=0.0,
        description=(
            "Most minutes one reclaim pass may spend. A large tree of small files "
            "takes tens of seconds to delete; a pass stops at this budget and the "
            "next one (or the first after a restart) finishes any directory it "
            "left half deleted, so no pass holds the backlog (#1983)."
        ),
    )

    reclaim_dry_run: bool = Field(
        default=False,
        description=(
            "Evaluate every workspace directory and log what would be reclaimed, "
            "and why the rest is kept, without renaming or deleting anything (#1983)."
        ),
    )

    page_webhook_url: str = Field(
        default="",
        description=(
            "Every change of the disk verdict (ok, low, critical) is POSTed here as "
            "JSON, once, so crossing the degraded threshold pages someone (PC-130). "
            "Empty disables paging."
        ),
    )

    def admission_floor_gib(self, max_concurrent: int) -> float:
        """GiB free below which admission is refused.

        SYN_DISK_REFUSE_ADMISSION_BELOW_GIB when set, else one run reserve per
        execution that can be in flight at once.
        """
        if self.refuse_admission_below_gib is not None:
            return self.refuse_admission_below_gib
        return self.run_reserve_gib * max_concurrent

    def admission_floor_basis(self, max_concurrent: int) -> str:
        """Where the admission floor came from, for the operator reading a refusal."""
        if self.refuse_admission_below_gib is not None:
            return "SYN_DISK_REFUSE_ADMISSION_BELOW_GIB"
        return (
            f"SYN_DISK_RUN_RESERVE_GIB={self.run_reserve_gib:g} per run x "
            f"SYN_EXECUTION_MAX_CONCURRENT={max_concurrent}"
        )

    def admission_floor_setting(self) -> str:
        """The setting that moves the admission floor as it is configured now."""
        if self.refuse_admission_below_gib is not None:
            return "SYN_DISK_REFUSE_ADMISSION_BELOW_GIB"
        return "SYN_DISK_RUN_RESERVE_GIB (or set SYN_DISK_REFUSE_ADMISSION_BELOW_GIB)"

    def degraded_floor_gib(self, max_concurrent: int) -> float:
        """GiB free below which /health degrades; never below the admission floor."""
        refuse = self.admission_floor_gib(max_concurrent)
        configured = (
            self.degraded_below_gib
            if self.degraded_below_gib is not None
            else DEGRADED_FLOOR_MULTIPLE * refuse
        )
        return max(configured, refuse)

    @model_validator(mode="after")
    def _floor_below_threshold(self) -> DiskSettings:
        # A floor above the warning threshold would refuse work while /health
        # still said the disk was fine, which is the silent refusal this
        # setting exists to replace.
        if (
            self.refuse_admission_below_percent is not None
            and self.degraded_below_percent is not None
            and self.refuse_admission_below_percent > self.degraded_below_percent
        ):
            raise ValueError(
                "SYN_DISK_REFUSE_ADMISSION_BELOW_PERCENT must not exceed "
                "SYN_DISK_DEGRADED_BELOW_PERCENT"
            )
        if (
            self.refuse_admission_below_gib is not None
            and self.degraded_below_gib is not None
            and self.refuse_admission_below_gib > self.degraded_below_gib
        ):
            raise ValueError(
                "SYN_DISK_REFUSE_ADMISSION_BELOW_GIB must not exceed SYN_DISK_DEGRADED_BELOW_GIB"
            )
        return self
