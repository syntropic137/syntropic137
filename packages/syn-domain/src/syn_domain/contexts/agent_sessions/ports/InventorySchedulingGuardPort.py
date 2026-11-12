"""Per-run mutual exclusion for inventory scheduling (#1534)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import RunIdentity


class InventorySchedulingGuardPort(Protocol):
    def hold(self, run: RunIdentity) -> AbstractAsyncContextManager[bool]:
        """Try once to hold ``run``'s scheduling guard for the block; yield whether it is held.

        Never waits. While one holder has it, every other process asking for
        the same run gets ``False`` until the block exits. Held across "is a job
        open?" and "schedule one", so two inventory managers cannot both pass
        the check for one run.
        """
        ...
