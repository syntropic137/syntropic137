"""The control-signal adapter `get_controller` falls back to without Redis.

Kept beside ``_wiring``; split out for the file-size fitness limit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_adapters.control.commands import ControlSignal


class _NullSignalQueueAdapter:
    """No-op signal adapter when Redis is not available."""

    async def enqueue(self, execution_id: str, signal: ControlSignal) -> None:
        pass

    async def dequeue(self, execution_id: str) -> ControlSignal | None:  # noqa: ARG002
        return None

    async def get_signal(self, execution_id: str) -> ControlSignal | None:  # noqa: ARG002
        return None
