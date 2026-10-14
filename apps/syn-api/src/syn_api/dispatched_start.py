"""What one dispatcher start does once it may run, and how its failure travels.

Split out of `_wiring_admission.py`, which decides WHEN a start runs - behind
the gate, in a budget slot, or inline into the run queue (#1310 1.3). The
bodies here are the same whichever of those it was, so both paths call them
and neither owns them. Nothing here imports from `_wiring_admission`, so the
dependency runs one way.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from syn_domain.contexts._shared.maintenance import carrying

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from syn_domain.contexts._shared.maintenance import AdmissionTicket
    from syn_domain.contexts.orchestration import (
        ExecuteWorkflowCommand,
        ExecuteWorkflowHandler,
        ExecutionRequestAggregate,
    )
    from syn_domain.contexts.orchestration.slices.start_resume import (
        StartFailureReporter,
        StartResumeHandler,
    )

logger = logging.getLogger(__name__)


class ExecutionRequests(Protocol):
    """Reads the durable record of an admitted direct start (#1557)."""

    async def get_by_id(self, aggregate_id: str) -> ExecutionRequestAggregate | None: ...


async def request_withdrawn(requests: ExecutionRequests, execution_id: str) -> bool:
    """Whether this direct start was withdrawn while it waited (#1650).

    Asked by BOTH direct start paths - the route's queued task and the request
    ProcessManager's - once the start holds its budget slot and immediately
    before it starts: the wait for a slot is where a withdrawal lands. The
    caller's `held` block then ends, so a withdrawn start gives its slot (and
    its admission lease) straight back.
    """
    from syn_domain.contexts.orchestration import execution_request_id

    request = await requests.get_by_id(execution_request_id(execution_id))
    if request is None or not request.withdrawn:
        return False
    logger.info("Not starting %s: its request was withdrawn while it waited", execution_id)
    return True


async def report_start_failure(
    start_key: str, on_failure: StartFailureReporter, exc: Exception
) -> None:
    """Hand the failure over; nothing awaits this task, so a failure to record it is logged."""
    try:
        await on_failure(exc)
    except Exception:
        logger.exception("Could not record the failed start", extra={"start": start_key})


async def admit_now(ticket: AdmissionTicket | None, start: Callable[[], Awaitable[None]]) -> None:
    """Run a start to its admission, here and now, under its lease (#1310 1.3).

    With the run queue a start ends at ``admitted``, so it is awaited inline
    and never spawned: no task carries an execution, and a refusal at the
    slot re-check is raised to the caller, which can still record it.
    """
    with carrying(ticket):
        if ticket is not None:
            await ticket.enter_slot()
        await start()


async def start_resume_now(
    resume_handler: StartResumeHandler,
    parent_execution_id: str,
    admitted: AdmissionTicket | None,
    on_failure: StartFailureReporter,
) -> None:
    """Start the child of ``parent_execution_id``, delivering any failure to ``on_failure``."""
    try:
        await resume_handler.handle(parent_execution_id, admitted=admitted)
    except Exception as exc:
        logger.exception(
            "Background resume start raised exception",
            extra={"parent_execution_id": parent_execution_id},
        )
        # A log alone left the to-do `dispatched` and re-offered for
        # ever, counting no attempt and recording no reason (#1463).
        # The record decides what the failure means; this only
        # delivers it.
        await report_start_failure(parent_execution_id, on_failure, exc)


async def start_requested_now(
    handler: ExecuteWorkflowHandler,
    requests: ExecutionRequests | None,
    command: ExecuteWorkflowCommand,
    admitted: AdmissionTicket | None,
    on_failure: StartFailureReporter,
) -> None:
    """Start an admitted direct request, unless it was withdrawn while it waited."""
    from syn_domain.contexts.orchestration import (
        DuplicateExecutionError,
        WorkflowNotFoundError,
    )

    execution_id = command.execution_id or ""
    if requests is not None and await request_withdrawn(requests, execution_id):
        return
    try:
        await handler.handle(command, admitted=admitted)
    except DuplicateExecutionError:
        # Its stream already exists: started, by this or another
        # process. The start event settles the record.
        logger.info("Requested execution %s already started", execution_id)
    except WorkflowNotFoundError as exc:
        # A refusal by recorded facts, so terminal: ValueError.
        await report_start_failure(execution_id, on_failure, ValueError(str(exc)))
    except Exception as exc:
        logger.exception(
            "Requested execution start raised exception",
            extra={"execution_id": execution_id},
        )
        await report_start_failure(execution_id, on_failure, exc)
