"""The startup half of #1387's wake-up: say "admission is open" again.

A deploy pauses admission, drains, and clears the flag - and clearing it is
what re-offers the dispatches it held back. That only works if a process is
alive to hear it, so every start says it again once its subscriptions are
live. Kept out of `lifecycle.py` because it is one decision with its own
reasons, not a step in the startup sequence's own logic.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from syn_api._wiring_admission import get_admission_gate

logger = logging.getLogger(__name__)


async def announce_admission_if_open() -> None:
    """Re-announce "admission is open" once subscriptions are running (#1387).

    This is what makes the wake-up survive a restart. Clearing maintenance mode
    announces, and the trigger-dispatch ProcessManager re-offers the dispatches
    the deploy paused - but only if a process is alive to receive it. A crash
    between the clear and the drain leaves `paused` records and no second
    prompt, because a flag that is already false never becomes false again.

    So every start says it again. The announcement is durable and idempotent,
    and lands strictly after the coordinator's live boundary - which is what
    takes this process out of catch-up, and so what decides whether the
    ProcessManager's processor side may run at all. Appending it first would
    make it backlog: delivered, recorded, and never acted on. That ordering is
    the caller's to establish, and `_init_subscriptions` establishes it by
    awaiting `coordinator.start()` before calling this - not by the order of
    two lines.

    Only when admission is actually open: announcing during a deploy would be
    false, and the dispatches would be refused and re-paused anyway.
    """
    gate = get_admission_gate()
    try:
        mode = await gate.current()
        if mode.active:
            logger.info("Admission is paused; no re-open announced at startup")
            return
        await gate.announce_open(mode, after_restart=True)
    except Exception:
        logger.exception(
            "Could not announce that admission is open at startup; triggers "
            "paused by a deploy wait for the next subscribed event (#1387)"
        )


#: How often a disk refusal is re-checked for recovery (#1560). Bounds how long
#: parked work waits after space is freed; a stat() per tick costs nothing.
DISK_RECOVERY_INTERVAL_SECONDS = 30.0

_disk_recovery_task: asyncio.Task[None] | None = None


async def announce_when_disk_recovers(
    interval_seconds: float = DISK_RECOVERY_INTERVAL_SECONDS,
) -> None:
    """Re-announce "admission is open" once a full disk has room again (#1560).

    The disk counterpart of clearing maintenance mode. A trigger or resume
    refused for a full disk is parked, and space coming back is not an event,
    so without this nothing wakes it on a quiet system. The gate decides
    whether there is anything to announce; this only supplies the clock.

    A failure is logged and retried on the next tick: the gate keeps its hold
    when the announcement does not land.
    """
    gate = get_admission_gate()
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            if await gate.announce_if_disk_recovered():
                logger.info("Disk space recovered; announced that admission is open (#1560)")
        except Exception:
            logger.exception(
                "Could not announce that admission is open after disk recovery; "
                "retrying in %ss (#1560)",
                interval_seconds,
            )


def start_disk_recovery_watch() -> None:
    """Start the watch, once. Called after subscriptions are live."""
    global _disk_recovery_task
    if _disk_recovery_task is not None and not _disk_recovery_task.done():
        return
    _disk_recovery_task = asyncio.create_task(
        announce_when_disk_recovers(), name="disk-recovery-announcer"
    )


async def stop_disk_recovery_watch() -> None:
    """Stop the watch; a no-op if never started."""
    global _disk_recovery_task
    task, _disk_recovery_task = _disk_recovery_task, None
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
