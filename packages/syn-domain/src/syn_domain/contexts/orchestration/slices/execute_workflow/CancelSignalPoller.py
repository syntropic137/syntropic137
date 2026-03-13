"""CancelSignalPoller — polls ExecutionController for CANCEL signals.

Isolates signal polling I/O from stream parsing logic.
No-op when controller is None.

Extracted from EventStreamProcessor.process_stream() (ISS-196).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_adapters.control import ExecutionController

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PollResult:
    """Result of a cancel signal poll."""

    should_interrupt: bool
    reason: str | None = None


class CancelSignalPoller:
    """Polls ExecutionController for CANCEL signals at configurable intervals.

    No-op when controller is None.
    """

    def __init__(
        self,
        controller: ExecutionController | None,
        execution_id: str,
        poll_interval: int = 10,
    ) -> None:
        self._controller = controller
        self._execution_id = execution_id
        self._poll_interval = poll_interval

    async def check(self, line_count: int) -> PollResult:
        """Check for cancel signal at poll boundaries.

        Returns PollResult with should_interrupt=True if CANCEL received.
        """
        if self._controller is None:
            return PollResult(should_interrupt=False)

        if line_count % self._poll_interval != 0:
            return PollResult(should_interrupt=False)

        from syn_adapters.control.commands import ControlSignalType

        signal = await self._controller.check_signal(self._execution_id)
        if signal and signal.signal_type == ControlSignalType.CANCEL:
            logger.info(
                "CANCEL signal received for execution %s at line %d — sending SIGINT",
                self._execution_id,
                line_count,
            )
            return PollResult(should_interrupt=True, reason=signal.reason)

        return PollResult(should_interrupt=False)
