"""What a trigger's start reports back to its dispatch record (#1707)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_domain.contexts._shared.maintenance import AdmissionTicket
    from syn_domain.contexts.orchestration.slices.start_resume import StartFailureReporter

logger = logging.getLogger(__name__)

StartConfirmer = Callable[[], Awaitable[None]]


class StartConfirmation:
    """Tells ``on_started`` once that a start is durable, and remembers it did.

    Called by the ticket at the durable write, and by the worker when `handle`
    finds the stream already there or returns without a ticket. Once called,
    an exception from the run is not a failure to start: the execution exists
    and records its own failure. A confirmation that could not be recorded
    leaves the record `queued`, so it is re-offered and settled as a duplicate.
    """

    def __init__(
        self,
        execution_id: str,
        on_started: StartConfirmer | None,
        on_held: StartFailureReporter | None,
    ) -> None:
        self._execution_id = execution_id
        self._on_started = on_started
        self._on_held = on_held
        self.confirmed = False

    def watch(self, admitted: AdmissionTicket | None) -> None:
        """Be told at ``admitted``'s durable write, not when the run ends."""
        if admitted is not None:
            admitted.on_durable(self)

    async def __call__(self) -> None:
        if self.confirmed:
            return
        self.confirmed = True
        if self._on_started is None:
            return
        try:
            await self._on_started()
        except Exception:
            logger.exception("Could not record the start", extra={"start": self._execution_id})

    async def failed(self, exc: Exception) -> None:
        """Hand ``exc`` over as a failed start, unless the start was already confirmed.

        Nothing awaits the worker's task, so a failure to record it is logged.
        """
        if self._on_held is None or self.confirmed:
            return
        try:
            await self._on_held(exc)
        except Exception:
            logger.exception(
                "Could not record the failed start", extra={"start": self._execution_id}
            )
