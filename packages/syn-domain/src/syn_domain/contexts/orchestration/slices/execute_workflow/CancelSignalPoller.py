"""CancelSignalPoller — polls ExecutionController for CANCEL signals.

Isolates signal polling I/O from stream parsing logic.
No-op when controller is None.

Polling is not left to the agent's output: a quiet agent produces no lines, and
a poll that waits for the next line waits for ever (#918). ``with_idle_ticks``
wraps the stream so a reader is woken every ``poll_seconds`` of silence, and
``check`` polls once that long has passed whatever the line count.

Extracted from EventStreamProcessor.process_stream() (ISS-196).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from syn_shared.control import ControlSignalType

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator

    from syn_adapters.control import ExecutionController

logger = logging.getLogger(__name__)

#: Longest a CANCEL waits to be seen, chatty agent or silent (#918).
CANCEL_POLL_SECONDS = 2.0


@dataclass(frozen=True)
class PollResult:
    """Result of a cancel signal poll."""

    should_interrupt: bool
    reason: str | None = None


class CancelSignalPoller:
    """Polls ExecutionController for CANCEL signals at configurable intervals.

    Polls every ``poll_interval`` lines, and on any call once ``poll_seconds``
    have passed since the last poll. No-op when controller is None.
    """

    def __init__(
        self,
        controller: ExecutionController | None,
        execution_id: str,
        poll_interval: int = 10,
        poll_seconds: float = CANCEL_POLL_SECONDS,
    ) -> None:
        self._controller = controller
        self._execution_id = execution_id
        self._poll_interval = poll_interval
        self.poll_seconds = poll_seconds
        self._last_poll = time.monotonic()

    async def check(self, line_count: int) -> PollResult:
        """Check for cancel signal at poll boundaries.

        Returns PollResult with should_interrupt=True if CANCEL received.
        """
        if self._controller is None:
            return PollResult(should_interrupt=False)

        overdue = time.monotonic() - self._last_poll >= self.poll_seconds
        if line_count % self._poll_interval != 0 and not overdue:
            return PollResult(should_interrupt=False)

        return await self.poll(line_count)

    async def poll(self, line_count: int) -> PollResult:
        """Ask the controller now, whatever the boundary: the stream has gone quiet."""
        if self._controller is None:
            return PollResult(should_interrupt=False)

        self._last_poll = time.monotonic()
        signal = await self._controller.check_signal(self._execution_id)
        if signal and signal.signal_type == ControlSignalType.CANCEL:
            logger.info(
                "CANCEL signal received for execution %s at line %d — stopping the agent",
                self._execution_id,
                line_count,
            )
            return PollResult(should_interrupt=True, reason=signal.reason)

        return PollResult(should_interrupt=False)


async def with_idle_ticks(
    stream: AsyncIterator[str], every_seconds: float
) -> AsyncGenerator[str | None]:
    """Yield ``stream``'s lines, and ``None`` after each ``every_seconds`` of silence.

    The pending read is kept across ticks, so no line is lost or reordered.
    Close the result (``contextlib.aclosing``) when stopping early: that is
    what cancels the read still waiting on the stream.
    """
    lines = aiter(stream)
    pending: asyncio.Future[str] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(anext(lines))
            done, _ = await asyncio.wait({pending}, timeout=every_seconds)
            if not done:
                yield None
                continue
            read, pending = pending, None
            try:
                line = read.result()
            except StopAsyncIteration:
                return
            yield line
    finally:
        if pending is not None:
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                await pending
