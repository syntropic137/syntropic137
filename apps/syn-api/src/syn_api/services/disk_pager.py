"""Page an operator when the workspace volume crosses a free-space threshold (PC-130).

/health saying ``degraded`` is only seen by someone who looks. On 2026-10-08
nobody looked until the volume was at 98%. So the same judge /health and
admission use (`DiskSpaceGuard`) is read on a clock, and every change of its
verdict - into ``low`` at 15% free, into ``critical`` at 5%, and back to
``ok`` - is POSTed once to ``SYN_DISK_PAGE_WEBHOOK_URL``. A state that has not
changed is not sent again; a delivery that failed is retried next tick.

The clock is `disk_pressure.DiskPressureMonitor`'s, which runs whether or not
a webhook is set and builds a pager only when one is (#1983).
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from syn_domain.contexts._shared.disk_space import DiskCheck

logger = logging.getLogger(__name__)


class DiskPage(BaseModel):
    """What the webhook receives."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: str
    previous_state: str
    path: str
    free_percent: float | None
    detail: str


@dataclass
class DiskPager:
    """Sends one page per change of the disk verdict."""

    check: Callable[[], DiskCheck]
    send: Callable[[DiskPage], Awaitable[None]]
    #: The last verdict delivered (or, at start, assumed): "ok" pages nothing.
    delivered: str = "ok"

    async def run_once(self) -> DiskPage | None:
        """Page if the verdict changed since the last delivery. Never raises."""
        try:
            check = self.check()
        except Exception:
            logger.warning("Disk pager could not read free space", exc_info=True)
            return None
        state = check.state.value
        if state == self.delivered:
            return None
        page = DiskPage(
            state=state,
            previous_state=self.delivered,
            path=check.path,
            free_percent=None if check.usage is None else round(check.usage.free_percent, 2),
            detail=check.detail,
        )
        try:
            await self.send(page)
        except Exception:
            logger.exception("Disk page (%s -> %s) not delivered; retrying", self.delivered, state)
            return None
        logger.warning("Disk page delivered: %s -> %s: %s", self.delivered, state, check.detail)
        self.delivered = state
        return page


def webhook_sender(url: str) -> Callable[[DiskPage], Awaitable[None]]:
    """POST the page as JSON; raises unless the webhook answers 2xx."""

    def post(page: DiskPage) -> None:
        request = urllib.request.Request(
            url,
            data=json.dumps(page.model_dump()).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError(f"disk page webhook answered {response.status}")

    async def send(page: DiskPage) -> None:
        await asyncio.to_thread(post, page)

    return send
