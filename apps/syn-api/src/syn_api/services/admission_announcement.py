"""The startup half of #1387's wake-up: say "admission is open" again.

A deploy pauses admission, drains, and clears the flag - and clearing it is
what re-offers the dispatches it held back. That only works if a process is
alive to hear it, so every start says it again once its subscriptions are
live. Kept out of `lifecycle.py` because it is one decision with its own
reasons, not a step in the startup sequence's own logic.
"""

from __future__ import annotations

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
