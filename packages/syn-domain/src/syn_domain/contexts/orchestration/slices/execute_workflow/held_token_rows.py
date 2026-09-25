"""Codex per-turn token rows, HELD until the model that ran is known (ADR-067 D9).

Codex never names its model on stdout; the rollout read at end-of-stream is the
first moment it is known, so a row written live could only say "unknown" about
a model that is about to be learned. ``CodexStreamProcessor`` holds its rows
here and flushes them once, after that read (and again in a ``finally``, which
finds nothing left if the first flush ran).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class HeldTurnUsage(Protocol):
    """The three per-turn figures a token_usage row is written from."""

    @property
    def fresh_input(self) -> int: ...
    @property
    def billable_output(self) -> int: ...
    @property
    def cache_read(self) -> int: ...


class TokenRowRecorder(Protocol):
    """The slice of the Lane-2 collector a flush needs."""

    def note_observed_model(self, model: str | None) -> None: ...

    async def record_token_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_creation: int = 0,
        cache_read: int = 0,
        model: str | None = None,
    ) -> None: ...


class HeldTokenRows:
    """Rows held until flushed; every held row is written exactly once."""

    def __init__(self, collector: TokenRowRecorder, phase_id: str) -> None:
        self._collector = collector
        self._phase_id = phase_id
        self._pending: list[HeldTurnUsage] = []
        #: Strong references to shielded flush tasks, so one that outlives a
        #: cancelled await is not garbage-collected mid-write.
        self._tasks: set[asyncio.Task[Exception | None]] = set()

    def hold(self, turn: HeldTurnUsage) -> None:
        self._pending.append(turn)

    async def flush(self, model: str | None, *, raise_errors: bool) -> None:
        """Write every held row, stamped with ``model``.

        The rows are handed to ONE task that owns them, and this await rides
        out any cancel until that task is done, then re-raises the cancel. So a
        cancel landing mid-flush (the second cancel of a cancelled run, say)
        neither interrupts the writes nor lets the run return while they are
        still in flight - where loop teardown could kill them. Every row is
        written exactly once; nothing is left pending for a later flush.

        Each row is attempted even if an earlier one fails. With
        ``raise_errors`` the first writer error is re-raised once every row
        has been tried; without it (the ``finally`` path, where an exception
        may already be propagating) errors are only logged.
        """
        self._collector.note_observed_model(model)
        pending, self._pending = self._pending, []
        if not pending:
            return
        writes = asyncio.create_task(self._write(pending, model))
        self._tasks.add(writes)
        writes.add_done_callback(self._tasks.discard)
        first_error = await _await_through_cancellation(writes)
        if first_error is not None and raise_errors:
            raise first_error

    async def _write(self, pending: list[HeldTurnUsage], model: str | None) -> Exception | None:
        first_error: Exception | None = None
        for turn in pending:
            try:
                await self._collector.record_token_usage(
                    turn.fresh_input,
                    turn.billable_output,
                    cache_creation=0,
                    cache_read=turn.cache_read,
                    model=model,
                )
            except Exception as err:
                logger.exception("Failed to record codex token usage (phase=%s)", self._phase_id)
                first_error = first_error or err
        return first_error


async def _await_through_cancellation[T](task: asyncio.Task[T]) -> T:
    """Await ``task`` to completion even if cancelled meanwhile, then re-raise.

    ``asyncio.shield`` alone protects the task but lets the CALLER return on
    cancel, leaving the task to finish unowned - and a loop torn down right
    after cancels it. Waiting here keeps ownership until the work is done.
    """
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.done():
                raise
            cancelled = True
            continue
        if cancelled:
            raise asyncio.CancelledError
        return result
