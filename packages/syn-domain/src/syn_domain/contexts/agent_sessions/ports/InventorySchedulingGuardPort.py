"""Per-run mutual exclusion for inventory scheduling (#1534, #2254)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import RunIdentity


class HeldInventorySchedule(Protocol):
    """One run's scheduling record, readable and writable only while its guard is held."""

    async def last_scheduled(self) -> str | None:
        """The job ID last recorded for the run, durable from the moment it was recorded.

        Unlike the job projection, this never lags the schedule: it is written
        under the guard before the job's request is saved (#2254).
        """
        ...

    async def record_scheduled(self, job_id: str) -> None:
        """Durably record ``job_id`` as the run's latest scheduled job."""
        ...


class InventorySchedulingGuardPort(Protocol):
    def hold(self, run: RunIdentity) -> AbstractAsyncContextManager[HeldInventorySchedule | None]:
        """Try once to hold ``run``'s scheduling guard for the block.

        Yields the run's schedule when held, ``None`` when another holder has
        it. Never waits. Held across "is a job open?" and "schedule one", so
        two inventory managers cannot both pass the check for one run.
        """
        ...
