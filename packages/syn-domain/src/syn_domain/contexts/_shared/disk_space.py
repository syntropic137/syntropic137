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

GIB FIRST, PERCENT ONLY IF ASKED FOR (#1947). A run needs a number of bytes,
not a share of the disk: 3.9% free of a 2 TB disk is 71 GiB, room for many
runs, while 6% of a 100 GB disk is 6 GiB. So both floors are absolute. A
percent floor is still honoured when an operator sets one, as a second way to
cross the same line: either floor crossed is enough.

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

from syn_domain.contexts._shared.admission_refusal import AdmissionRefusedError

logger = logging.getLogger(__name__)

GIB = 2**30

#: Where self-host settings live, named in every refusal so the operator knows
#: which file to edit when the floor itself is wrong for their host.
SELFHOST_ENV_FILE = "~/.syntropic137/.env"


def format_gib(num_bytes: float) -> str:
    """Bytes as GiB to one decimal, without a trailing ``.0``."""
    return f"{num_bytes / GIB:.1f}".removesuffix(".0")


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


def _below_percent(usage: DiskUsage, percent: float | None) -> bool:
    return percent is not None and usage.free_percent < percent


@dataclass(frozen=True)
class DiskThresholds:
    """The floors one filesystem is judged against.

    The two byte floors always apply. A percent floor applies only when set,
    and crossing either kind is enough. ``refuse_basis`` says where the
    admission floor came from, for the operator reading a refusal.
    """

    refuse_admission_below_bytes: int
    degraded_below_bytes: int
    refuse_basis: str
    refuse_admission_below_percent: float | None = None
    degraded_below_percent: float | None = None

    @classmethod
    def from_gib(
        cls,
        *,
        refuse_admission_below_gib: float,
        degraded_below_gib: float,
        refuse_basis: str,
        refuse_admission_below_percent: float | None = None,
        degraded_below_percent: float | None = None,
    ) -> DiskThresholds:
        return cls(
            refuse_admission_below_bytes=int(refuse_admission_below_gib * GIB),
            degraded_below_bytes=int(degraded_below_gib * GIB),
            refuse_basis=refuse_basis,
            refuse_admission_below_percent=refuse_admission_below_percent,
            degraded_below_percent=degraded_below_percent,
        )

    def refuses(self, usage: DiskUsage) -> bool:
        return usage.free_bytes < self.refuse_admission_below_bytes or _below_percent(
            usage, self.refuse_admission_below_percent
        )

    def degrades(self, usage: DiskUsage) -> bool:
        return usage.free_bytes < self.degraded_below_bytes or _below_percent(
            usage, self.degraded_below_percent
        )

    def describe(self) -> str:
        degraded = f"degraded below {format_gib(self.degraded_below_bytes)} GiB"
        if self.degraded_below_percent is not None:
            degraded += f" or {self.degraded_below_percent:g}%"
        refused = (
            f"new executions refused below {format_gib(self.refuse_admission_below_bytes)} GiB"
        )
        if self.refuse_admission_below_percent is not None:
            refused += f" or {self.refuse_admission_below_percent:g}%"
        return f"{degraded}; {refused} ({self.refuse_basis})"


@dataclass(frozen=True)
class DiskCheck:
    """The verdict and the facts behind it, as /health publishes them."""

    path: str
    state: DiskState
    usage: DiskUsage | None
    thresholds: DiskThresholds

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
            f"{format_gib(self.usage.free_bytes)} GiB free on {self.path} "
            f"({self.usage.free_percent:.1f}% of {format_gib(self.usage.total_bytes)} GiB); "
            f"{self.thresholds.describe()}."
        )

    @property
    def remedy(self) -> str:
        """What to do: free space, or move the floor if it is wrong for this host."""
        floors = "SYN_DISK_REFUSE_ADMISSION_BELOW_GIB or SYN_DISK_RUN_RESERVE_GIB"
        if self.thresholds.refuse_admission_below_percent is not None:
            floors += " (or unset SYN_DISK_REFUSE_ADMISSION_BELOW_PERCENT)"
        return (
            f"To recover, free space on {self.path}: delete finished workspace "
            "directories there and run `docker image prune`, then retry. If the "
            f"floor is wrong for this host, lower {floors} in {SELFHOST_ENV_FILE} "
            "and restart the API."
        )


class InsufficientDiskSpaceError(AdmissionRefusedError):
    """Raised instead of admitting an execution below the free-space floor.

    Carries the check so the entry point can answer in its own protocol (507
    over HTTP) and say exactly how much space is left.
    """

    hold_reason = "insufficient_disk_space"

    def __init__(self, check: DiskCheck) -> None:
        super().__init__(
            "Refusing to start a new execution: the workspace volume is nearly full. "
            + check.detail
            + " "
            + check.remedy
        )
        self.check = check


class DiskSpaceGuard:
    """Judges the workspace volume against the configured thresholds."""

    def __init__(self, port: DiskSpacePort, thresholds: DiskThresholds) -> None:
        self._port = port
        self._thresholds = thresholds

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
            thresholds=self._thresholds,
        )

    def refuse_if_full(self) -> None:
        """Raise `InsufficientDiskSpaceError` when below the admission floor."""
        check = self.check()
        if check.refuses_admission:
            raise InsufficientDiskSpaceError(check)

    def _judge(self, usage: DiskUsage | None) -> DiskState:
        if usage is None:
            return DiskState.UNMEASURABLE
        if self._thresholds.refuses(usage):
            return DiskState.CRITICAL
        if self._thresholds.degrades(usage):
            return DiskState.LOW
        return DiskState.OK
