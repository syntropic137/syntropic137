"""Process-local maintenance mode. Tests and offline only (ADR-060)."""

from __future__ import annotations

from datetime import UTC, datetime

from syn_adapters.in_memory import InMemoryAdapter
from syn_domain.contexts._shared import MaintenanceMode

__all__ = ["InMemoryMaintenanceAdapter"]


class InMemoryMaintenanceAdapter(InMemoryAdapter):
    """Correct within one process, lost on restart.

    Inherits :class:`InMemoryAdapter` so constructing it outside a test or
    offline environment raises. Losing this state on restart is precisely the
    failure #1387 is about: the API container comes back permissive in the
    middle of the deploy that set the flag.
    """

    def __init__(self) -> None:
        super().__init__()
        self._mode = MaintenanceMode()

    async def current(self) -> MaintenanceMode:
        return self._mode

    async def set_mode(self, *, active: bool, reason: str, actor: str) -> MaintenanceMode:
        self._mode = MaintenanceMode(
            active=active,
            reason=reason,
            since=datetime.now(UTC) if active else None,
            actor=actor,
        )
        return self._mode
