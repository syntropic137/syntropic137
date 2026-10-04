"""A `POST /execute` start: recorded durably, then queued for a budget slot (#1557).

The record is what makes the 200 true across a restart. The queued task is
only the fast path: while it holds the start's budget claim the request
ProcessManager leaves the record alone, and if this process dies first the
ProcessManager starts the request from the record instead.
"""

from __future__ import annotations

import logging
import weakref
from typing import TYPE_CHECKING

from syn_api._wiring_admission import get_execution_budget
from syn_api.execution_budget import StartAlreadyClaimedError, StartPath
from syn_domain.contexts._shared.maintenance import carrying, guarantee_settled

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastapi import BackgroundTasks

    from syn_domain.contexts._shared import AdmissionTicket
    from syn_domain.contexts.orchestration import RequestExecutionCommand

logger = logging.getLogger(__name__)


async def record_execution_request(
    command: RequestExecutionCommand, admitted: AdmissionTicket
) -> None:
    """Write the request's `ExecutionRequested` before the caller hears 200.

    Called inside the gate (#1387). The admission lease is NOT ended here: the
    start still waits for a budget slot, and a planned drain keeps waiting for
    it exactly as it does for a queued trigger start. What the record adds is
    the crash case: a process that dies anyway leaves a request the request
    ProcessManager starts. A write that fails ends the lease and raises - the
    caller answers 500 and nothing was admitted.
    """
    from syn_adapters.storage.repositories import get_execution_request_repository
    from syn_domain.contexts.orchestration import ExecutionRequestAggregate

    request = ExecutionRequestAggregate()
    request.request(command)
    try:
        await get_execution_request_repository().save_new(request)
    except BaseException:
        admitted.abort()
        raise


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
    try:
        claim = budget.claim(execution_id, workflow_id=workflow_id, path=StartPath.DIRECT)
    except StartAlreadyClaimedError:
        # The request ProcessManager saw the durable request first and already
        # queued its start in this process, under its own lease. Not a second
        # start, and not a failure: the 200 is still true.
        admitted.abort()
        return

    async def _run() -> None:
        # #1387: the lease, carried across the hop that used to spend it. It
        # ends inside `execute()` when the execution's start event is durable,
        # or here if this task produced no execution at all, and it spans the
        # wait for a budget slot, as on the trigger path.
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
