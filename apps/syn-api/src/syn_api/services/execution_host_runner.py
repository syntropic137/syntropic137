"""Run this process's ExecutionHost when the Run Queue is on (#1310 1.5, ADR-072).

With ``SYN_EXECUTION_RUN_QUEUE_ENABLED`` off, ``get_execution_run_queue`` is
None and nothing here starts: the flag-off path is main's. With it on, admission
only writes the queue (1.3), so without this nothing would ever drain an
admitted run. Until the role split (1.6) the API process is the one executor,
so the startup reap in ``lifecycle`` stays as it is: no other host is live.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket

from syn_adapters.execution_host import AggregateRunInterrupter, ExecutionHost
from syn_adapters.storage.repositories import (
    get_execution_event_stream,
    get_workflow_execution_repository,
)
from syn_adapters.workspace_backends.host_labels import (
    LABEL_HOST_GENERATION,
    LABEL_HOST_ID,
    host_labels,
)
from syn_api._wiring import get_execution_processor, get_execution_run_queue
from syn_api.services.dead_host_reaper import DockerDeadHostReaper
from syn_domain.contexts.orchestration import ORCHESTRATION_EVENT_EPOCH
from syn_domain.contexts.orchestration.ports import ExecutorHost
from syn_shared.settings import get_settings

logger = logging.getLogger(__name__)

_host_task: asyncio.Task[None] | None = None


async def start_execution_host() -> None:
    """Start the claim loop, once; a no-op with the Run Queue off.

    The host id is the ``syn.host_id`` label this process stamps on its
    containers, so a reconciler's reap of this host finds exactly them.
    """
    global _host_task
    if _host_task is not None and not _host_task.done():
        return
    queue = await get_execution_run_queue()
    if queue is None:
        return
    labels = host_labels()
    host = ExecutorHost(
        host_id=labels[LABEL_HOST_ID],
        container_id=socket.gethostname(),
        generation=labels[LABEL_HOST_GENERATION],
        epoch=ORCHESTRATION_EVENT_EPOCH,
    )
    executor = ExecutionHost(
        queue,
        host,
        capacity=get_settings().execution.max_concurrent,
        drainer=await get_execution_processor(),
        reaper=DockerDeadHostReaper(),
        interrupter=AggregateRunInterrupter(get_workflow_execution_repository()),
        streams=get_execution_event_stream(),
    )
    _host_task = asyncio.create_task(executor.run_until_drained(), name="execution-host")
    _host_task.add_done_callback(_report_exit)
    logger.info("ExecutionHost %s claiming from the Run Queue", host.host_id)


async def stop_execution_host() -> None:
    """Cancel the loop: held runs take the interruption path, rows await their lease."""
    global _host_task
    task, _host_task = _host_task, None
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


def _report_exit(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            "ExecutionHost stopped: admitted runs will not be claimed by this process",
            exc_info=(type(exc), exc, exc.__traceback__),
        )
