"""Queue a `POST /execute` start behind its lease and its budget slot (#1387, #1557)."""

from __future__ import annotations

import logging
import weakref
from typing import TYPE_CHECKING

from syn_api._wiring_admission import get_execution_budget
from syn_api.execution_budget import StartPath
from syn_domain.contexts._shared.maintenance import carrying, guarantee_settled

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastapi import BackgroundTasks

    from syn_domain.contexts._shared import AdmissionTicket

logger = logging.getLogger(__name__)


def queue_direct_start(
    background_tasks: BackgroundTasks,
    *,
    execution_id: str,
    workflow_id: str,
    admitted: AdmissionTicket,
    start: Callable[[], Awaitable[None]],
) -> None:
    """Claim the start's budget slot and queue it, both inside the caller's gate.

    The claim is taken HERE, beside `add_task`, so the execution is findable as
    `queued` from the moment the 200 says it started (#1557). It is the ONE
    budget trigger and resume starts claim from too.
    """
    budget = get_execution_budget()
    claim = budget.claim(execution_id, workflow_id=workflow_id, path=StartPath.DIRECT)

    async def _run() -> None:
        # #1387: the lease, carried across the hop that used to spend it.
        # `add_task` only queues this coroutine - Starlette runs it after the
        # response - so the ticket cannot be released there. It ends inside
        # `execute()` when the execution's start event is durable, or here if
        # this task produced no execution at all. It spans the wait for a
        # budget slot, as on the trigger path: queued work is admitted work.
        with carrying(admitted):
            try:
                async with budget.held(claim):
                    await start()
            except Exception:
                logger.exception(
                    "Workflow execution raised exception",
                    extra={"execution_id": execution_id, "workflow_id": workflow_id},
                )

    background_tasks.add_task(_run)
    # Starlette runs queued tasks after the response is sent, and promises
    # nothing about a response that is never sent - a client that goes away
    # mid-send, a middleware that replaces the response. `_run` would then never
    # be entered, so its `carrying` would never settle and the next deploy's
    # `PUT /maintenance` would wait on this lease forever, and the claim would
    # hold a budget slot for ever. Bind both to the queued callable itself,
    # which outlives this call for exactly as long as Starlette may still call
    # it (#1387).
    weakref.finalize(_run, budget.release, claim)
    guarantee_settled(admitted, _run)
