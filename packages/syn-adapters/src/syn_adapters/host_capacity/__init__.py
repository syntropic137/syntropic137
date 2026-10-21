"""Reads this host's cores, memory, free disk and CPU pressure for the execution budget (#1715)."""

from __future__ import annotations

import os
from pathlib import Path

from syn_domain.contexts._shared.host_capacity import HostCapacity

_CPU_PRESSURE = Path("/proc/pressure/cpu")


class ProcHostCapacity:
    """`HostCapacityPort` over ``os`` and ``/proc``. Raises ``OSError`` if a read fails.

    Cores are the CPUs this process may be scheduled on, which a cgroup cpuset
    narrows; memory is physical RAM. Workspaces run as sibling containers on
    the same host, so this is the capacity they share.
    """

    def __init__(self, disk_path: str, pressure_file: Path = _CPU_PRESSURE) -> None:
        self._disk_path = disk_path
        self._pressure_file = pressure_file

    def read(self) -> HostCapacity:
        stat = os.statvfs(self._disk_path)
        return HostCapacity(
            cpu_cores=float(len(os.sched_getaffinity(0))),
            memory_bytes=os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"),
            disk_free_bytes=stat.f_bavail * stat.f_frsize,
            cpu_pressure_avg60=self._cpu_pressure_avg60(),
        )

    def _cpu_pressure_avg60(self) -> float | None:
        """The ``some avg60`` of PSI, or None on a kernel without it."""
        try:
            text = self._pressure_file.read_text()
        except OSError:
            return None
        return parse_cpu_pressure_avg60(text)


def parse_cpu_pressure_avg60(text: str) -> float | None:
    """``some avg10=0.00 avg60=1.25 ...`` -> 1.25; None if the line is not there."""
    for line in text.splitlines():
        fields = line.split()
        if fields and fields[0] == "some":
            for field in fields[1:]:
                key, _, value = field.partition("=")
                if key == "avg60":
                    return float(value)
    return None


def build_host_capacity() -> ProcHostCapacity:
    """The reader over the configured workspace volume, the same one the disk guard reads."""
    from syn_shared.env_constants import ENV_SYN_WORKSPACE_CONTAINER_DIR
    from syn_shared.settings import get_settings

    path = get_settings().disk.path or os.environ.get(
        ENV_SYN_WORKSPACE_CONTAINER_DIR, "/workspaces"
    )
    return ProcHostCapacity(path)
