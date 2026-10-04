"""Free space on the workspace volume, judged once for /health and admission (#1560).

Workspace directories share a filesystem with Postgres on a single-host
deployment. When that filesystem filled, nothing said so until an execution
reached a Postgres write and failed with ENOSPC, mid-run, after paying for
everything before it. This module turns the same measurement into two earlier
answers: /health goes degraded below one threshold, and admission refuses new
executions below a lower floor.

ONE JUDGEMENT, TWO READERS. `DiskSpaceGuard.check()` is the only place the
thresholds are compared, so /health and admission cannot disagree about one
filesystem. The measurement is a port, so tests never touch a real disk.

AN UNMEASURABLE DISK IS REPORTED, NOT REFUSED. If the path cannot be measured
(misconfigured mount, missing directory), /health says so as degraded, but
admission does not refuse on that alone: a refusal must name a fact, and "I
could not look" would block every execution on a configuration typo.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiskUsage:
    """One measurement of a filesystem."""

    free_bytes: int
    total_bytes: int

    @property
    def free_percent(self) -> float:
        """Percent of the filesystem still free. A zero-sized one is 0% free."""
        if self.total_bytes <= 0:
            return 0.0
        return 100.0 * self.free_bytes / self.total_bytes


class DiskSpacePort(Protocol):
    """Measures the filesystem holding the workspace volume.

    Raises ``OSError`` when it cannot: that is reported as unmeasurable, never
    as full and never as fine.
    """

    @property
    def path(self) -> str: ...

    def usage(self) -> DiskUsage: ...


class DiskState(StrEnum):
    """What the free space means, most severe last."""

    OK = "ok"
    UNMEASURABLE = "unmeasurable"
    LOW = "low"
    CRITICAL = "critical"


@dataclass(frozen=True)
class DiskCheck:
    """The verdict and the facts behind it, as /health publishes them."""

    path: str
    state: DiskState
    usage: DiskUsage | None
    degraded_below_percent: float
    refuse_admission_below_percent: float

    @property
    def is_degraded(self) -> bool:
        return self.state is not DiskState.OK

    @property
    def refuses_admission(self) -> bool:
        return self.state is DiskState.CRITICAL

    @property
    def detail(self) -> str:
        """One line an operator can act on."""
        if self.usage is None:
            return f"Free space on {self.path} could not be measured."
        return (
            f"{self.usage.free_percent:.1f}% free on {self.path} "
            f"({self.usage.free_bytes // 2**30} GiB of {self.usage.total_bytes // 2**30} GiB); "
            f"degraded below {self.degraded_below_percent:g}%, "
            f"new executions refused below {self.refuse_admission_below_percent:g}%."
        )


class InsufficientDiskSpaceError(Exception):
    """Raised instead of admitting an execution below the free-space floor.

    Carries the check so the entry point can answer in its own protocol (507
    over HTTP) and say exactly how much space is left.
    """

    def __init__(self, check: DiskCheck) -> None:
        super().__init__(
            "Refusing to start a new execution: the workspace volume is nearly full. "
            + check.detail
            + " Free space (old workspace directories under the workspace volume, "
            "unused Docker images) and retry."
        )
        self.check = check


class DiskSpaceGuard:
    """Judges the workspace volume against the configured thresholds."""

    def __init__(
        self,
        port: DiskSpacePort,
        *,
        degraded_below_percent: float,
        refuse_admission_below_percent: float,
    ) -> None:
        self._port = port
        self._degraded_below = degraded_below_percent
        self._refuse_below = refuse_admission_below_percent

    def check(self) -> DiskCheck:
        """Measure now and judge. Never raises."""
        try:
            usage = self._port.usage()
        except OSError:
            logger.warning("Could not measure free space on %s", self._port.path, exc_info=True)
            usage = None
        return DiskCheck(
            path=self._port.path,
            state=self._judge(usage),
            usage=usage,
            degraded_below_percent=self._degraded_below,
            refuse_admission_below_percent=self._refuse_below,
        )

    def refuse_if_full(self) -> None:
        """Raise `InsufficientDiskSpaceError` when below the admission floor."""
        check = self.check()
        if check.refuses_admission:
            raise InsufficientDiskSpaceError(check)

    def _judge(self, usage: DiskUsage | None) -> DiskState:
        if usage is None:
            return DiskState.UNMEASURABLE
        if usage.free_percent < self._refuse_below:
            return DiskState.CRITICAL
        if usage.free_percent < self._degraded_below:
            return DiskState.LOW
        return DiskState.OK
