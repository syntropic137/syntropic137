"""Admission wiring - how an execution is let in, and how the answer travels.

Three things that only make sense together, which is why they are one module
rather than three corners of the composition root (#1387):

* :func:`get_maintenance_port` - the durable answer to "may anything new be
  admitted", chosen by ADR-060 priority with no permissive fallback;
* :func:`get_admission_gate` - the one object per process that may decide, so
  that admitting and flipping the flag exclude each other;
* :class:`BackgroundWorkflowDispatcher` - the one place where the decision and
  the work it authorises come apart, because the work is a fire-and-forget
  task. It carries the ticket from the gate to the durable write, so a drain
  cannot return over an execution that has been admitted but not yet stored.

The composition of the dispatcher with its handler stays in `_wiring.py`
beside the handler itself; nothing here imports from there, so the dependency
runs one way.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_domain.contexts._shared.maintenance import (
        AdmissionGate,
        AdmissionTicket,
        MaintenancePort,
    )
    from syn_domain.contexts._shared.repository_ref import RepositoryRef
    from syn_domain.contexts.orchestration import ExecuteWorkflowHandler

from syn_adapters.storage import get_event_store_client
from syn_domain.contexts._shared.maintenance import carrying, guarantee_settled

logger = logging.getLogger(__name__)


_maintenance_singleton: MaintenancePort | None = None


def get_maintenance_port() -> MaintenancePort:
    """Return the process-wide maintenance mode store (#1387).

    The single durable answer to "may a new execution be admitted". Every
    admission path reads it; the deploy script sets it before draining and
    clears it after the swap.

    Priority (ADR-060): Postgres (durable) > Redis (durable) > in-memory
    (tests only) > fail-fast. There is deliberately no permissive fallback: an
    API that cannot read the flag cannot know admission is open, and guessing
    "open" is exactly the silent re-opening this gate exists to prevent.

    A singleton for the connection, not for the state - both durable adapters
    read through to their store on every call, so a container that starts in
    the middle of a deploy comes up still refusing.
    """
    global _maintenance_singleton
    if _maintenance_singleton is not None:
        return _maintenance_singleton

    from syn_shared.settings import get_settings

    settings = get_settings()

    if settings.uses_in_memory_stores:
        from syn_adapters.maintenance import InMemoryMaintenanceAdapter

        _maintenance_singleton = InMemoryMaintenanceAdapter()
        return _maintenance_singleton

    if settings.syn_observability_db_url:
        try:
            from syn_api._wiring_db import get_shared_db_pool

            pool = get_shared_db_pool()
            if pool is not None:
                from syn_adapters.maintenance import PostgresMaintenanceAdapter

                logger.info("Maintenance mode using Postgres (ADR-060)")
                _maintenance_singleton = PostgresMaintenanceAdapter(pool)  # type: ignore[arg-type]  # asyncpg.Pool vs AsyncConnectionPool
                return _maintenance_singleton
        except Exception:
            logger.warning(
                "Postgres maintenance store unavailable; falling back to Redis",
                exc_info=True,
            )

    try:
        from syn_adapters.maintenance import RedisMaintenanceAdapter
        from syn_adapters.redis_client import resilient_redis_client

        logger.info("Maintenance mode using Redis")
        _maintenance_singleton = RedisMaintenanceAdapter(resilient_redis_client(settings.redis_url))
        return _maintenance_singleton
    except Exception as exc:
        raise RuntimeError(
            "No durable maintenance-mode backend available (Postgres and Redis both "
            "failed). Configure SYN_OBSERVABILITY_DB_URL or REDIS_URL for production. "
            "See ADR-060 (docs/adrs/ADR-060-restart-safe-trigger-deduplication.md) "
            "and issue #1387."
        ) from exc


_admission_gate_singleton: AdmissionGate | None = None


def get_admission_gate() -> AdmissionGate:
    """Return the process-wide admission gate (#1387).

    One instance per process, and that is load-bearing rather than tidiness:
    the gate's guarantee is mutual exclusion between admitting an execution and
    changing the flag, and two instances over the same store exclude nothing.
    So the ``PUT /maintenance`` route, the HTTP execute route and the trigger
    dispatcher all have to reach admission through this, never through
    :func:`get_maintenance_port` directly.

    The port under it stays the durable one (Postgres > Redis > fail-fast); the
    gate adds ordering, not storage, and caches no state of its own.

    The announcer is the other half of #1387: clearing the flag is not an event
    and wakes nobody, so re-opening writes `maintenance.AdmissionOpen` to the
    event store and the trigger-dispatch ProcessManager - which subscribes to
    it - re-offers the dispatches a deploy held back.
    """
    global _admission_gate_singleton
    if _admission_gate_singleton is not None:
        return _admission_gate_singleton

    from syn_adapters.maintenance import EventStoreAdmissionAnnouncer
    from syn_domain.contexts._shared import AdmissionGate as _AdmissionGate

    _admission_gate_singleton = _AdmissionGate(
        get_maintenance_port(),
        EventStoreAdmissionAnnouncer(get_event_store_client()),
    )
    return _admission_gate_singleton


class BackgroundWorkflowDispatcher:
    """Bridges WorkflowDispatchProjection → ExecuteWorkflowHandler.

    - run_workflow() → handler.handle() bridge
    - Fire-and-forget via asyncio.Task (never blocks projection loop)
    - Tracks tasks for graceful shutdown
    - Semaphore-bounded concurrency (Phase A2)
    """

    def __init__(
        self,
        handler: ExecuteWorkflowHandler,
        max_concurrent: int = 1,
        maintenance: AdmissionGate | None = None,
    ) -> None:
        """`max_concurrent` defaults to 1 for the same reason the setting does.

        A caller that omits it used to get 5, which quietly reintroduced the
        unsafe value the setting exists to avoid (#865). The safe value has to
        be the one you get by saying nothing.

        `maintenance` is the :class:`AdmissionGate` (#1387), not the bare port:
        this class is where the decision to admit and the task that carries it
        out come apart, so it needs the thing that can hold them together.
        """
        self._handler = handler
        self._tasks: set[asyncio.Task[None]] = set()
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._maintenance = maintenance

    async def run_workflow(
        self,
        workflow_id: str,
        inputs: dict[str, str],
        execution_id: str = "",
        task: str | None = None,
        repos: list[RepositoryRef] | None = None,
    ) -> AdmissionTicket | None:
        # SYNCHRONOUS refusal, before the task exists (#1039). Everything after
        # this line is fire-and-forget: `WorkflowDispatchProjection` awaits
        # this method and then writes `status="dispatched"`, so anything that
        # fails inside the task leaves a trigger record claiming a run that has
        # no execution stream and never will. Raising HERE reaches the
        # projection's `dispatch_exception` path, which marks the record
        # `failed` - the state that is actually true.
        #
        # #1387 rides the same slot for the same reason. The projection tells
        # the two apart by exception type and records this one as `paused`, not
        # `failed`: the trigger was refused, not broken.
        if self._maintenance is None:
            await self._handler.validate_stored_declarations(workflow_id)
            self._spawn(workflow_id, inputs, execution_id, task, repos, None)
            return None

        # Two reads, and they are not the same check twice. This first one is
        # cheap and unlocked, so a paused gate costs no template read and a
        # deploy is never delayed behind one. It decides nothing: its answer
        # can be stale by the time it arrives.
        await self._maintenance.refuse_early()

        await self._handler.validate_stored_declarations(workflow_id)

        # The decisive one. Inside `admitting()` no maintenance transition can
        # complete, and the task is created before the ticket is spent - so
        # once `PUT /maintenance` returns, no task can still be on its way in.
        # The ticket outlives this block: it is spent where the execution
        # becomes durable, so `PUT /maintenance` also cannot return over a task
        # that is still queued behind the semaphore.
        # A refusal here is raised, synchronously, out of this method and into
        # the projection, which is the only place it can still change what the
        # trigger record says.
        async with self._maintenance.admitting() as ticket:
            self._spawn(workflow_id, inputs, execution_id, task, repos, ticket)
            return ticket

    def _spawn(
        self,
        workflow_id: str,
        inputs: dict[str, str],
        execution_id: str,
        task: str | None,
        repos: list[RepositoryRef] | None,
        ticket: AdmissionTicket | None,
    ) -> None:
        """Create the fire-and-forget task. Synchronous, so nothing interleaves
        between the gate's answer and the work existing.

        Creating it does not spend the ticket (#1387). The task may sit behind
        the semaphore for as long as the execution ahead of it runs, and until
        it opens its stream the drain cannot see it - so the lease it carries
        is ended by the task itself, not by this line.

        Ended by the task, not by its BODY. `shutdown()` can cancel a task
        between `create_task` and its first turn, and a coroutine torn down
        before it ever ran reaches no `finally` of its own - so the lease is
        also bound to the task's completion here, which the loop reports for
        every outcome including that one.
        """
        asyncio_task = asyncio.create_task(
            self._run_with_semaphore(
                workflow_id, inputs, execution_id, task=task, repos=repos, admitted=ticket
            ),
            name=f"workflow-exec-{execution_id or workflow_id}",
        )
        self._tasks.add(asyncio_task)
        asyncio_task.add_done_callback(self._tasks.discard)
        guarantee_settled(ticket, asyncio_task)

    async def _run_with_semaphore(
        self,
        workflow_id: str,
        inputs: dict[str, str],
        execution_id: str,
        task: str | None = None,
        repos: list[RepositoryRef] | None = None,
        admitted: AdmissionTicket | None = None,
    ) -> None:
        # #1387: the lease spans the semaphore wait. This is the case that
        # rebuilt the execution-loss window - a ticket spent at `create_task`
        # while the execution sat queued behind another one, invisible to the
        # drain. `carrying` ends the lease however this task leaves: the
        # execution became durable and ended it already, `_run` swallowed a
        # failure, or shutdown cancelled us while still queued. It ends the
        # lease at the moment the body stops rather than a loop turn later;
        # `_spawn`'s backstop covers the body that never starts at all.
        with carrying(admitted):
            async with self._semaphore:
                await self._run(
                    workflow_id, inputs, execution_id, task=task, repos=repos, admitted=admitted
                )

    async def _run(
        self,
        workflow_id: str,
        inputs: dict[str, str],
        execution_id: str,
        task: str | None = None,
        repos: list[RepositoryRef] | None = None,
        admitted: AdmissionTicket | None = None,
    ) -> None:
        from syn_domain.contexts.orchestration import (
            DuplicateExecutionError,
            ExecuteWorkflowCommand,
        )

        try:
            cmd = ExecuteWorkflowCommand(
                aggregate_id=workflow_id,
                inputs=inputs or {},
                repos=repos or [],
                execution_id=execution_id or None,
                task=task,
            )
            # #1387: carry the gate's answer in rather than asking again. This
            # runs after the caller was told the work started, so a second
            # refusal here could only lose the execution, never prevent it.
            await self._handler.handle(cmd, admitted=admitted)
        except DuplicateExecutionError:
            logger.info(
                "Duplicate dispatch for execution %s, already running",
                execution_id,
            )
        except Exception:
            logger.exception(
                "Background workflow execution raised exception",
                extra={"workflow_id": workflow_id, "execution_id": execution_id},
            )

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
