"""How often the kernel has held this container back for exceeding its CPU limit.

WHY (#1600): the API was capped at 0.5 CPU while nine workspaces took 2 each,
and the only symptom was a 55 s /sessions read. Nothing said "the control
plane is being throttled". cgroup v2 counts exactly that in ``cpu.stat``:
``nr_periods`` scheduling periods, ``nr_throttled`` of them cut short, and
``throttled_usec`` spent waiting. A rising ``nr_throttled / nr_periods`` is the
signal to raise ``API_CPU_LIMIT``.

UNKNOWN IS A STATE, NOT A ZERO. On cgroup v1, outside a container, or when the
cpu controller is not enabled for this cgroup, the counters do not exist. That
is reported as ``status="unknown"`` with null counters, never as 0 throttled,
which would read as "measured, and fine".
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

#: cgroup v2 unified hierarchy. Inside a container with a private cgroup
#: namespace (Docker's default on v2) this is the container's own cgroup.
CGROUP_V2_CPU_STAT = Path("/sys/fs/cgroup/cpu.stat")


class CpuThrottling(BaseModel):
    """CPU throttling of the process answering /health, since its cgroup was created."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["measured", "unknown"] = Field(
        description="'measured' when cgroup v2 cpu.stat reported throttling counters; "
        "'unknown' on cgroup v1, outside a container, or with no CPU limit set. "
        "Unknown is not zero: the counters are null, not 0.",
    )
    nr_periods: int | None = Field(
        default=None, description="Scheduling periods in which this cgroup was runnable."
    )
    nr_throttled: int | None = Field(
        default=None,
        description="Periods in which the cgroup hit its CPU limit and was held back. "
        "nr_throttled / nr_periods is the share of time the control plane was starved.",
    )
    throttled_usec: int | None = Field(
        default=None, description="Total time spent throttled, in microseconds."
    )


_UNKNOWN = CpuThrottling(status="unknown")


def read_cpu_throttling(cpu_stat: Path = CGROUP_V2_CPU_STAT) -> CpuThrottling:
    """Throttling counters from a cgroup v2 ``cpu.stat`` file, or ``unknown``.

    Never raises: a probe that can take /health down is worse than no probe.
    """
    try:
        text = cpu_stat.read_text()
    except OSError:
        return _UNKNOWN

    counters: dict[str, int] = {}
    for line in text.splitlines():
        key, _, value = line.partition(" ")
        if value.strip().isdigit():
            counters[key] = int(value)

    try:
        return CpuThrottling(
            status="measured",
            nr_periods=counters["nr_periods"],
            nr_throttled=counters["nr_throttled"],
            throttled_usec=counters["throttled_usec"],
        )
    except KeyError:
        # The file exists but the cpu controller is not enabled for this
        # cgroup, so only usage is counted; throttling cannot be said.
        logger.debug("cpu.stat at %s has no throttling counters", cpu_stat)
        return _UNKNOWN
