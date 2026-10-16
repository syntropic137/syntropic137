"""Watch free space and wake the reclaimer when it runs low (#1983).

Until #1983 the only thing reading the disk verdict on a clock was the pager,
and the pager did not start without ``SYN_DISK_PAGE_WEBHOOK_URL``. So on a
deployment with no webhook nothing reacted to a filling disk at all: the
reclaimer waited out its 30-minute clock while admission closed.

The monitor now runs unconditionally. Every tick it reads the same judge
/health and admission use (`DiskSpaceGuard`), sets the pressure event on each
entry into ``low`` or ``critical`` so a reclaim pass starts at once, and hands
the same verdict to the pager, which exists only when a webhook is set.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from syn_api.services.disk_pager import DiskPager
    from syn_domain.contexts._shared.disk_space import DiskCheck

logger = logging.getLogger(__name__)

#: How often the verdict is read; a stat() per tick costs nothing.
DISK_PRESSURE_INTERVAL_SECONDS = 60.0

#: Verdicts that wake the reclaimer on entry.
PRESSURE_STATES = frozenset({"low", "critical"})


@dataclass
class DiskPressureMonitor:
    """Reads the disk verdict; wakes the reclaimer and feeds the pager."""

    check: Callable[[], DiskCheck]
    wake: asyncio.Event
    pager: DiskPager | None = None
    #: The verdict read last tick; "ok" at start, so starting low wakes at once.
    previous: str = "ok"
    latest: DiskCheck | None = field(default=None)

    async def run_once(self) -> str | None:
        """Read the verdict, wake on entry into pressure, page. Never raises."""
        try:
            check = self.check()
        except Exception:
            logger.warning("Disk pressure monitor could not read free space", exc_info=True)
            return None
        self.latest = check
        state = check.state.value
        if state in PRESSURE_STATES and self.previous not in PRESSURE_STATES:
            logger.warning("Disk %s (%s): waking the workspace reclaimer", state, check.detail)
            self.wake.set()
        self.previous = state
        if self.pager is not None:
            await self.pager.run_once()
        return state


async def monitor_on_a_clock(monitor: DiskPressureMonitor, interval_seconds: float) -> None:
    while True:
        await monitor.run_once()
        await asyncio.sleep(interval_seconds)


_pressure: asyncio.Event | None = None
_monitor_task: asyncio.Task[None] | None = None


def pressure_event() -> asyncio.Event:
    """The one event the monitor sets and the reclaimer waits on."""
    global _pressure
    if _pressure is None:
        _pressure = asyncio.Event()
    return _pressure


def start_disk_pressure_monitor() -> None:
    """Start the monitor, once, webhook or not. The pager rides along when one is set."""
    global _monitor_task
    if _monitor_task is not None and not _monitor_task.done():
        return
    from syn_api._wiring_admission import get_disk_space_guard
    from syn_api.services.disk_pager import DiskPager, webhook_sender
    from syn_shared.settings import get_settings

    guard = get_disk_space_guard()
    url = get_settings().disk.page_webhook_url
    monitor = DiskPressureMonitor(check=guard.check, wake=pressure_event())
    if url:
        # The pager judges the verdict the monitor just read, not a second stat().
        monitor.pager = DiskPager(
            check=lambda: monitor.latest if monitor.latest is not None else guard.check(),
            send=webhook_sender(url),
        )
    else:
        logger.warning("SYN_DISK_PAGE_WEBHOOK_URL is not set; low disk space pages nobody")
    _monitor_task = asyncio.create_task(
        monitor_on_a_clock(monitor, DISK_PRESSURE_INTERVAL_SECONDS), name="disk-pressure"
    )


async def stop_disk_pressure_monitor() -> None:
    """Stop the monitor; a no-op if never started."""
    global _monitor_task
    task, _monitor_task = _monitor_task, None
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
