"""What startup resolves for each process role (ADR-072 D1, #1310 1.6).

One image, two roles. The previous process's executions are the API's to
resolve, and only while the Run Queue is off: then every execution ran inside
the API, so whatever is still ``running`` when it starts is provably orphaned.
With the queue on, a live executor beside a restarting API may be mid-run, and
a global sweep would fail its sessions; its claimed runs are fenced on Lease
expiry and reaped by its own ``syn.host_id`` instead (ADR-072 D5, D6).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from syn_api.services.execution_host_runner import resolve_previous_process
from syn_api.services.reconciliation import reconcile_orphaned_sessions
from syn_shared.settings import get_settings

if TYPE_CHECKING:
    from datetime import datetime

    from syn_shared.settings.execution import ProcessRole

logger = logging.getLogger(__name__)


class RoleScoped(Protocol):
    """A startup service that says whether only an API process starts it."""

    @property
    def api_only(self) -> bool: ...


def current_role() -> ProcessRole:
    """This process's role, as SYN_EXECUTION_PROCESS_ROLE pins it."""
    return get_settings().execution.process_role


def role_services[S: RoleScoped](registry: tuple[S, ...], role: ProcessRole) -> tuple[S, ...]:
    """The registry entries a process of this role starts (ADR-072 D1)."""
    return tuple(e for e in registry if role.serves_api or not e.api_only)


async def resolve_previous_world(role: ProcessRole, *, started_before: datetime) -> None:
    """Main's startup session and execution reconcile, where it is still true.

    An executor never runs it: beside a flag-off API, the global reap would
    take the API's in-process containers. With the Run Queue on no role runs
    it, because "still running" no longer means "orphaned".
    """
    if not role.serves_api:
        return
    if get_settings().execution.run_queue_enabled:
        logger.info("Run Queue on: session reconcile is left to Lease expiry (ADR-072 D5)")
        return
    await reconcile_orphaned_sessions()
    await resolve_previous_process(started_before=started_before)
