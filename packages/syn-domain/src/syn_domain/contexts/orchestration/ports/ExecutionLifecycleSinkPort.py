"""Where an execution's end is told (#1661)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.slices.notify_execution_lifecycle.value_objects import (
        ExecutionLifecycleNotice,
    )


class ExecutionLifecycleSinkPort(Protocol):
    """Delivers one `ExecutionLifecycleNotice` to something outside the platform.

    MUST be idempotent per `notice.key`, (execution_id, outcome): a delivery
    retried after a crash, or offered twice, reaches the outside world once.

    Called live only, never while events are replayed: a rebuilt read model
    must not tell anyone again about executions that ended long ago.

    Raises when the delivery did not happen, so the notice stays owed and is
    offered again; returning means it was delivered.
    """

    async def deliver(self, notice: ExecutionLifecycleNotice) -> None: ...
