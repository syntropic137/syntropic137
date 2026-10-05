"""Measures the workspace volume for the disk-space guard (#1560)."""

from __future__ import annotations

import os

from syn_domain.contexts._shared.disk_space import DiskSpaceGuard, DiskUsage


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

    disk = get_settings().disk
    path = disk.path or os.environ.get(ENV_SYN_WORKSPACE_CONTAINER_DIR, "/workspaces")
    return DiskSpaceGuard(
        StatvfsDiskSpace(path),
        degraded_below_percent=disk.degraded_below_percent,
        refuse_admission_below_percent=disk.refuse_admission_below_percent,
    )
