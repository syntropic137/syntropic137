"""Process-local import ledger. Tests and offline only (ADR-060)."""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
from typing import TYPE_CHECKING

from syn_adapters.in_memory import InMemoryAdapter
from syn_domain.contexts.agent_sessions import BilledUsage

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

__all__ = ["InMemoryImportLedger"]


class InMemoryImportLedger(InMemoryAdapter):
    """Correct within one process, lost on restart.

    Inherits :class:`InMemoryAdapter` so constructing it outside a test or
    offline environment raises. A ledger is exactly the kind of state ADR-060
    is about: losing it silently reverts to double-billing, and nothing in the
    system reports that it happened.
    """

    def __init__(self) -> None:
        super().__init__()
        self._marks: dict[tuple[str, str], BilledUsage] = {}
        self._locks: defaultdict[tuple[str, str], asyncio.Lock] = defaultdict(asyncio.Lock)

    async def already_billed(self, execution_id: str, harness_session_id: str) -> BilledUsage:
        return self._marks.get((execution_id, harness_session_id), BilledUsage())

    async def record_billed(
        self, execution_id: str, harness_session_id: str, billed: BilledUsage
    ) -> None:
        """Monotonic per bucket, matching the Postgres adapter's GREATEST.

        The in-memory one is what the unit tests exercise, so it has to have
        the same semantics or the tests certify behaviour production does not
        have.
        """
        key = (execution_id, harness_session_id)
        previous = self._marks.get(key, BilledUsage())
        self._marks[key] = BilledUsage(
            uncached_input_tokens=max(previous.uncached_input_tokens, billed.uncached_input_tokens),
            cache_read_tokens=max(previous.cache_read_tokens, billed.cache_read_tokens),
            cache_creation_tokens=max(previous.cache_creation_tokens, billed.cache_creation_tokens),
            output_tokens=max(previous.output_tokens, billed.output_tokens),
        )

    @contextlib.asynccontextmanager
    async def guard(self, execution_id: str, harness_session_id: str) -> AsyncIterator[None]:
        """Per-key mutual exclusion within this event loop.

        `asyncio.Lock` is loop-affine, which is fine here: an in-process ledger
        is only correct within one process anyway, and the API runs one loop.
        """
        async with self._locks[(execution_id, harness_session_id)]:
            yield
