"""One writer at a time over a read-then-write the store cannot make atomic.

A projection store has no conditional write (InMemory: a dict set; Postgres: a
blind upsert), so "read the record, decide, save" is three awaits, and a second
writer in the same process can land between the read and the save and be
overwritten. Holding a `Transition` across the sequence closes that gap.

A separate type rather than a bare `asyncio.Lock` because of what it exposes.
Projection and process-manager modules may import only a whitelist
(`event_sourcing.fitness.projection_purity`), and `asyncio` is rightly not on
it: it is also `create_task`, subprocesses and sockets. Mutual exclusion is none
of those. It performs no I/O and outlives nothing, so replaying through a holder
of one still yields the same records with zero external calls. This is the
one piece of `asyncio` such a module needs, and nothing else.

In-process only: two processes writing the same projection would need a lock
in the store itself.
"""

from __future__ import annotations

import asyncio


class Transition:
    """An async context manager admitting one holder at a time, in order."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> None:
        await self._lock.acquire()

    async def __aexit__(self, *exc_info: object) -> None:
        self._lock.release()
