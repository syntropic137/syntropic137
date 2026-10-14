"""Measures the workspace volume for the disk-space guard (#1560)."""

from __future__ import annotations

import os

from syn_domain.contexts._shared.disk_space import DiskSpaceGuard, DiskThresholds, DiskUsage


class StatvfsDiskSpace:
    """`DiskSpacePort` over ``os.statvfs``. Raises ``OSError`` if the path is gone."""

    def __init__(self, path: str) -> None:
        self._path = path

    @property
    def path(self) -> str:
        return self._path

    def usage(self) -> DiskUsage:
        stat = os.statvfs(self._path)
        # f_bavail, not f_bfree: blocks reserved for root are not space an
        # unprivileged Postgres or agent can write into.
        return DiskUsage(
            free_bytes=stat.f_bavail * stat.f_frsize,
            total_bytes=stat.f_blocks * stat.f_frsize,
        )


def build_disk_space_guard() -> DiskSpaceGuard:
    """The guard over the configured workspace volume, from `DiskSettings`."""
    from syn_shared.env_constants import ENV_SYN_WORKSPACE_CONTAINER_DIR
    from syn_shared.settings import get_settings

    settings = get_settings()
    disk = settings.disk
    # The admission floor scales with concurrency (#1947): one run reserve per
    # execution that can be in flight, so each has room to finish.
    max_concurrent = settings.execution.max_concurrent
    path = disk.path or os.environ.get(ENV_SYN_WORKSPACE_CONTAINER_DIR, "/workspaces")
    return DiskSpaceGuard(
        StatvfsDiskSpace(path),
        DiskThresholds.from_gib(
            refuse_admission_below_gib=disk.admission_floor_gib(max_concurrent),
            degraded_below_gib=disk.degraded_floor_gib(max_concurrent),
            refuse_basis=disk.admission_floor_basis(max_concurrent),
            refuse_admission_below_percent=disk.refuse_admission_below_percent,
            degraded_below_percent=disk.degraded_below_percent,
        ),
    )
