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
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

if TYPE_CHECKING:
    from syn_domain.contexts._shared.maintenance import (
        AdmissionGate,
        AdmissionTicket,
        MaintenancePort,
    )
    from syn_domain.contexts._shared.repository_ref import RepositoryRef
    from syn_domain.contexts.orchestration import (
        EvalChoice,
        ExecuteWorkflowCommand,
        ExecuteWorkflowHandler,
        ExecutionRequestAggregate,
        LaunchEval,
    )
    from syn_domain.contexts.orchestration.slices.start_resume import (
        ResumeChild,
        StartFailureReporter,
        StartResumeHandler,
    )

from syn_adapters.storage import get_event_store_client, get_workflow_repository
from syn_adapters.storage.repositories import get_eval_repository
from syn_api.execution_budget import (
    ExecutionBudget,
    StartAlreadyClaimedError,
    StartClaim,
    StartPath,
)
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


_execution_budget_singleton: ExecutionBudget | None = None


def get_execution_budget() -> ExecutionBudget:
    """Return the process-wide execution budget (#1557).

    One per process, for the same reason as the admission gate: a limit is only
    a limit if every start path claims from the same one. `POST /execute`, the
    trigger dispatcher and resume starts all reach it through here, sized by
    `SYN_EXECUTION_MAX_CONCURRENT`.
    """
    global _execution_budget_singleton
    if _execution_budget_singleton is None:
        from syn_shared.settings import get_settings

        _execution_budget_singleton = ExecutionBudget(get_settings().execution.max_concurrent)
    return _execution_budget_singleton


async def admitted_launch_eval(workflow_id: str, choice: EvalChoice) -> LaunchEval:
    """The eval a dispatcher-started run joins, given its choice and the workflow's default.

    A trigger names no eval, so its run joins the workflow's default (#967).
    """
    from syn_domain.contexts.orchestration import WorkflowNotFoundError, launch_eval_for

    workflow = await get_workflow_repository().get_by_id(workflow_id)
    if workflow is None:
        raise WorkflowNotFoundError(workflow_id)
    return await launch_eval_for(get_eval_repository(), choice, workflow.default_eval_id)


#: Builds a :class:`StartResumeHandler` on demand. See the constructor for why
#: this is not simply the handler.
ResumeHandlerFactory = Callable[[], Awaitable["StartResumeHandler"]]
#: The eval a launch of this workflow joins, given what it asked for, admitted (#967).
LaunchEvalResolver = Callable[[str, "EvalChoice"], Awaitable["LaunchEval"]]


class ExecutionRequests(Protocol):
    """Reads the durable record of an admitted direct start (#1557)."""

    async def get_by_id(self, aggregate_id: str) -> ExecutionRequestAggregate | None: ...


class BackgroundWorkflowDispatcher:
    """Bridges WorkflowDispatchProjection → ExecuteWorkflowHandler.

    - run_workflow() → handler.handle() bridge
    - Fire-and-forget via asyncio.Task (never blocks projection loop)
    - Tracks tasks for graceful shutdown
    - Every start claims a slot in the process-wide execution budget (#1557)
    """

    def __init__(
        self,
        handler: ExecuteWorkflowHandler,
        max_concurrent: int = 1,
        maintenance: AdmissionGate | None = None,
        resume_handler: StartResumeHandler | ResumeHandlerFactory | None = None,
        budget: ExecutionBudget | None = None,
        requests: ExecutionRequests | None = None,
        launch_eval_for_workflow: LaunchEvalResolver | None = None,
    ) -> None:
        """``budget`` is the ONE execution budget every start path shares (#1557).

        Production passes the process-wide one, which `POST /execute` claims
        from too; a dispatcher with its own budget would bound only itself,
        which is the defect #1557 removed. ``max_concurrent`` only sizes a
        private budget for a caller that passes none, and stays 1 so that
        saying nothing is never the permissive answer.

        `maintenance` is the :class:`AdmissionGate` (#1387), not the bare port:
        this class is where the decision to admit and the task that carries it
        out come apart, so it needs the thing that can hold them together.
        """
        self._handler = handler
        # #967: a trigger names no eval, so its run joins the workflow's
        # default. Resolved once per trigger, when it is accepted and before it
        # queues, so neither the queue nor the handler re-resolves it. None:
        # every run is ordinary.
        self._launch_eval_for_workflow = launch_eval_for_workflow
        self._tasks: set[asyncio.Task[None]] = set()
        self._budget = budget if budget is not None else ExecutionBudget(max_concurrent)
        self._maintenance = maintenance
        # Either the handler, or something that will build it on first resume.
        #
        # A FACTORY is accepted because building the handler eagerly drags the
        # execution processor, the execution repository and therefore the
        # observability event store into DISPATCHER CONSTRUCTION - so an
        # unconfigured `SYN_OBSERVABILITY_DB_URL` stopped the dispatcher being
        # built at all, even for a deployment that never resumes anything. The
        # dispatcher's job is dispatching; a resume's dependencies are a resume's
        # problem, and they are resolved when one is actually requested.
        self._resume_handler: StartResumeHandler | None = (
            None if callable(resume_handler) else resume_handler
        )
        self._resume_handler_factory: ResumeHandlerFactory | None = (
            resume_handler if callable(resume_handler) else None
        )
        #: Where admitted direct starts are recorded (#1557). Read when one is
        #: offered for a start that is not already queued here - after a
        #: restart, or when the route's own task never ran.
        self._requests = requests

    @property
    def budget(self) -> ExecutionBudget:
        """The execution budget this dispatcher's starts claim from."""
        return self._budget

    async def _resolved_resume_handler(self) -> StartResumeHandler:
        """The resume handler, built on first use and kept.

        Raises the same RuntimeError as before when this dispatcher was given
        neither a handler nor a way to make one - a caller asking to resume
        without that is a wiring bug, not a runtime condition.
        """
        if self._resume_handler is None and self._resume_handler_factory is not None:
            self._resume_handler = await self._resume_handler_factory()
        if self._resume_handler is None:
            msg = "This dispatcher was built without a StartResumeHandler"
            raise RuntimeError(msg)
        return self._resume_handler

    def holds_start(self, parent_execution_id: str) -> bool:
        """Whether the child of this parent's resume is queued or running here (#1557)."""
        return self._budget.resume_of(parent_execution_id) is not None

    async def start_resume(
        self, parent_execution_id: str, *, on_failure: StartFailureReporter
    ) -> AdmissionTicket | None:
        """Start the child a resumed parent admitted, behind the same gate.

        Bridges ResumeStartProcessManager -> StartResumeHandler (ADR-014 s7) with
        `run_workflow`'s shape and for its reasons: the refusals - a closed
        gate (#1387), a child that may not start (#1454) - are raised HERE,
        synchronously, where the to-do list can still record them; the start
        itself runs as a task that claims a slot in the execution budget, and
        what fails in there is handed to ``on_failure`` (#1463).

        A second start for a child already queued or running here is a no-op,
        not a second task (#1557). The process manager no longer offers one,
        and this holds even for a caller that does.
        """
        if self.holds_start(parent_execution_id):
            logger.info("The resume start of %s is already queued or running", parent_execution_id)
            return None
        resume_handler = await self._resolved_resume_handler()
        if self._maintenance is None:
            child = await resume_handler.validate(parent_execution_id)
            self._spawn_resume(parent_execution_id, child, None, on_failure)
            return None
        await self._maintenance.refuse_early()
        child = await resume_handler.validate(parent_execution_id)
        async with self._maintenance.admitting() as ticket:
            self._spawn_resume(parent_execution_id, child, ticket, on_failure)
            return ticket

    def _spawn_resume(
        self,
        parent_execution_id: str,
        child: ResumeChild,
        ticket: AdmissionTicket | None,
        on_failure: StartFailureReporter,
    ) -> None:
        """`_spawn`, for a resume start: the lease is ended by the task."""
        claim = self._claim(
            child.execution_id,
            workflow_id=child.workflow_id,
            path=StartPath.RESUME,
            resumed_from=parent_execution_id,
            ticket=ticket,
        )
        if claim is None:
            return
        asyncio_task = asyncio.create_task(
            self._start_resume_in_budget(parent_execution_id, claim, ticket, on_failure),
            name=f"resume-start-{parent_execution_id}",
        )
        self._track(asyncio_task, claim, ticket)

    def _claim(
        self,
        execution_id: str,
        *,
        workflow_id: str,
        path: StartPath,
        ticket: AdmissionTicket | None,
        resumed_from: str | None = None,
    ) -> StartClaim | None:
        """Claim the start's place, or None - with the lease ended - for a duplicate.

        Synchronous with the task creation that follows, so the duplicate check
        and the claim cannot be split by another start (#1557).
        """
        try:
            return self._budget.claim(
                execution_id, workflow_id=workflow_id, path=path, resumed_from=resumed_from
            )
        except StartAlreadyClaimedError:
            logger.info("Not starting %s twice: it is already queued or running", execution_id)
            if ticket is not None:
                ticket.abort()
            return None

    def _track(
        self, asyncio_task: asyncio.Task[None], claim: StartClaim, ticket: AdmissionTicket | None
    ) -> None:
        """Keep the task for shutdown, and bind its lease and claim to its end.

        Both are released by the task's DONE callback as well as by its body,
        because a task cancelled before its first turn runs no line of its body
        (#1387's reasoning, applied to the budget claim too).
        """
        self._tasks.add(asyncio_task)
        asyncio_task.add_done_callback(self._tasks.discard)
        asyncio_task.add_done_callback(lambda _task: self._budget.release(claim))
        guarantee_settled(ticket, asyncio_task)

    async def _start_resume_in_budget(
        self,
        parent_execution_id: str,
        claim: StartClaim,
        admitted: AdmissionTicket | None,
        on_failure: StartFailureReporter,
    ) -> None:
        resume_handler = await self._resolved_resume_handler()
        with carrying(admitted):
            async with self._budget.held(claim):
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
                    await self._report_start_failure(parent_execution_id, on_failure, exc)

    @staticmethod
    async def _report_start_failure(
        start_key: str, on_failure: StartFailureReporter, exc: Exception
    ) -> None:
        """Hand the failure over; a failure to record it is only logged.

        Nothing awaits this task, so a raise here would vanish into the event
        loop's handler instead.
        """
        try:
            await on_failure(exc)
        except Exception:
            logger.exception("Could not record the failed start", extra={"start": start_key})

    def holds_request(self, execution_id: str) -> bool:
        """Whether this requested execution's start is queued or running here (#1557)."""
        return self._budget.position(execution_id) is not None

    async def start_requested(
        self, execution_id: str, *, on_failure: StartFailureReporter
    ) -> AdmissionTicket | None:
        """Start an admitted direct request from its durable record (#1557).

        `ExecutionRequestStartProcessManager` -> here, with `start_resume`'s
        shape: refusals are raised synchronously so the to-do list can record
        them, the start runs as a task that claims a budget slot, and what fails
        inside it is handed to ``on_failure``. A start already queued or running
        here is a no-op; one whose execution already exists is refused by the
        execution stream's NoStream write and counts as started.
        """
        if self.holds_request(execution_id):
            return None
        if self._requests is None:
            msg = "This dispatcher was built without an execution request repository"
            raise RuntimeError(msg)
        request = await self._requests.get_by_id(execution_id)
        if request is None or request.workflow_id is None:
            msg = f"No execution request {execution_id}"
            raise ValueError(msg)
        from syn_domain.contexts.orchestration import ExecuteWorkflowCommand

        command = ExecuteWorkflowCommand(
            aggregate_id=request.workflow_id,
            inputs=request.inputs,
            repos=request.repos,
            execution_id=execution_id,
            task=request.task,
            tags=request.tags,
            launch_eval=await self._requested_launch_eval(request),
        )
        if self._maintenance is not None:
            await self._maintenance.refuse_early()
        await self._handler.validate_stored_declarations(command.aggregate_id)
        if self._maintenance is None:
            self._spawn_requested(command, None, on_failure)
            return None
        async with self._maintenance.admitting() as ticket:
            self._spawn_requested(command, ticket, on_failure)
            return ticket

    async def _requested_launch_eval(self, request: ExecutionRequestAggregate) -> LaunchEval | None:
        """The eval the request was accepted into, carried unchanged (#967).

        Resolved at acceptance and recorded on the request, so a start that
        waited for a slot, or is recovered after a restart, joins that eval at
        those SHAs even if the workflow's default changed since. Only a request
        recorded before it carried that answer resolves its choice here, once.
        """
        if request.launch_eval is not None:
            return request.launch_eval
        if self._launch_eval_for_workflow is None or request.workflow_id is None:
            return None
        return await self._launch_eval_for_workflow(request.workflow_id, request.eval_choice)

    def _spawn_requested(
        self,
        command: ExecuteWorkflowCommand,
        ticket: AdmissionTicket | None,
        on_failure: StartFailureReporter,
    ) -> None:
        execution_id = command.execution_id or ""
        claim = self._claim(
            execution_id, workflow_id=command.aggregate_id, path=StartPath.DIRECT, ticket=ticket
        )
        if claim is None:
            return
        asyncio_task = asyncio.create_task(
            self._start_requested_in_budget(command, claim, ticket, on_failure),
            name=f"request-start-{execution_id}",
        )
        self._track(asyncio_task, claim, ticket)

    async def _start_requested_in_budget(
        self,
        command: ExecuteWorkflowCommand,
        claim: StartClaim,
        admitted: AdmissionTicket | None,
        on_failure: StartFailureReporter,
    ) -> None:
        from syn_domain.contexts.orchestration import (
            DuplicateExecutionError,
            WorkflowNotFoundError,
        )

        with carrying(admitted):
            async with self._budget.held(claim):
                try:
                    await self._handler.handle(command, admitted=admitted)
                except DuplicateExecutionError:
                    # Its stream already exists: started, by this or another
                    # process. The start event settles the record.
                    logger.info("Requested execution %s already started", claim.execution_id)
                except WorkflowNotFoundError as exc:
                    # A refusal by recorded facts, so terminal: ValueError.
                    await self._report_start_failure(
                        claim.execution_id, on_failure, ValueError(str(exc))
                    )
                except Exception as exc:
                    logger.exception(
                        "Requested execution start raised exception",
                        extra={"execution_id": claim.execution_id},
                    )
                    await self._report_start_failure(claim.execution_id, on_failure, exc)

    async def run_workflow(
        self,
        workflow_id: str,
        inputs: dict[str, str],
        execution_id: str = "",
        task: str | None = None,
        repos: list[RepositoryRef] | None = None,
    ) -> AdmissionTicket | None:
        # Named HERE, before the start is queued, so a start waiting for a slot
        # has an id to be found by (#1557). The handler would mint the same
        # shape later; minting it first only moves the moment.
        if not execution_id.startswith("exec-"):
            execution_id = f"exec-{uuid4().hex[:12]}"
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
            launch_eval = await self._launch_eval(workflow_id)
            self._spawn(workflow_id, inputs, execution_id, task, repos, None, launch_eval)
            return None

        # Two reads, and they are not the same check twice. This first one is
        # cheap and unlocked, so a paused gate costs no template read and a
        # deploy is never delayed behind one. It decides nothing: its answer
        # can be stale by the time it arrives.
        await self._maintenance.refuse_early()

        await self._handler.validate_stored_declarations(workflow_id)
        launch_eval = await self._launch_eval(workflow_id)

        # The decisive one. Inside `admitting()` no maintenance transition can
        # complete, and the task is created before the ticket is spent - so
        # once `PUT /maintenance` returns, no task can still be on its way in.
        # The ticket outlives this block: it is spent where the execution
        # becomes durable, so `PUT /maintenance` also cannot return over a task
        # that is still queued for an execution-budget slot.
        # A refusal here is raised, synchronously, out of this method and into
        # the projection, which is the only place it can still change what the
        # trigger record says.
        async with self._maintenance.admitting() as ticket:
            self._spawn(workflow_id, inputs, execution_id, task, repos, ticket, launch_eval)
            return ticket

    async def _launch_eval(self, workflow_id: str) -> LaunchEval | None:
        """The eval this trigger joins, resolved and admitted NOW, at acceptance (#967).

        Not in the task: it may wait for a budget slot while the workflow's
        default eval changes, and a trigger accepted into one eval must not
        start in another. Synchronous for the same reason as the refusals
        above: a missing or archived eval marks the trigger record `failed`.
        """
        if self._launch_eval_for_workflow is None:
            return None
        from syn_domain.contexts.orchestration import EvalChoice

        return await self._launch_eval_for_workflow(workflow_id, EvalChoice())

    def _spawn(
        self,
        workflow_id: str,
        inputs: dict[str, str],
        execution_id: str,
        task: str | None,
        repos: list[RepositoryRef] | None,
        ticket: AdmissionTicket | None,
        launch_eval: LaunchEval | None,
    ) -> None:
        """Claim the start's place and create its fire-and-forget task. Synchronous,
        so nothing interleaves between the gate's answer and the work existing.

        Creating it does not spend the ticket (#1387). The task may wait for a
        budget slot for as long as the executions ahead of it run, and until
        it opens its stream the drain cannot see it - so the lease it carries
        is ended by the task itself, not by this line.

        Ended by the task, not by its BODY. `shutdown()` can cancel a task
        between `create_task` and its first turn, and a coroutine torn down
        before it ever ran reaches no `finally` of its own - so the lease is
        also bound to the task's completion here, which the loop reports for
        every outcome including that one.
        """
        claim = self._claim(
            execution_id, workflow_id=workflow_id, path=StartPath.TRIGGER, ticket=ticket
        )
        if claim is None:
            return
        asyncio_task = asyncio.create_task(
            self._run_in_budget(
                workflow_id,
                inputs,
                claim,
                task=task,
                repos=repos,
                admitted=ticket,
                launch_eval=launch_eval,
            ),
            name=f"workflow-exec-{execution_id}",
        )
        self._track(asyncio_task, claim, ticket)

    async def _run_in_budget(
        self,
        workflow_id: str,
        inputs: dict[str, str],
        claim: StartClaim,
        task: str | None = None,
        repos: list[RepositoryRef] | None = None,
        admitted: AdmissionTicket | None = None,
        launch_eval: LaunchEval | None = None,
    ) -> None:
        # #1387: the lease spans the wait for a slot. This is the case that
        # rebuilt the execution-loss window - a ticket spent at `create_task`
        # while the execution sat queued behind another one, invisible to the
        # drain. `carrying` ends the lease however this task leaves: the
        # execution became durable and ended it already, `_run` swallowed a
        # failure, or shutdown cancelled us while still queued. It ends the
        # lease at the moment the body stops rather than a loop turn later;
        # `_track`'s backstop covers the body that never starts at all.
        with carrying(admitted):
            async with self._budget.held(claim):
                await self._run(
                    workflow_id,
                    inputs,
                    claim.execution_id,
                    task=task,
                    repos=repos,
                    admitted=admitted,
                    launch_eval=launch_eval,
                )

    async def _run(
        self,
        workflow_id: str,
        inputs: dict[str, str],
        execution_id: str,
        task: str | None = None,
        repos: list[RepositoryRef] | None = None,
        admitted: AdmissionTicket | None = None,
        launch_eval: LaunchEval | None = None,
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
                launch_eval=launch_eval,
            )
            # #1387: carry the gate's answer in rather than asking again. This
            # runs after the caller was told the work started, so a second
            # refusal here could only lose the execution, never prevent it.
            result = await self._handler.handle(cmd, admitted=admitted)
        except DuplicateExecutionError:
            logger.info(
                "Duplicate dispatch for execution %s, already running",
                execution_id,
            )
            return
        except Exception:
            logger.exception(
                "Background workflow execution raised exception",
                extra={"workflow_id": workflow_id, "execution_id": execution_id},
            )
            return
        if result.unrecorded_work_error is not None:
            # #1547: a trigger has no caller to hand an error to, so this log is
            # the report. It is also the only place outside process memory that
            # names the refs until the processor's next settle records them.
            logger.error(
                "Workflow execution failed",
                extra={
                    "execution_id": result.execution_id,
                    "workflow_id": workflow_id,
                    "error": result.unrecorded_work_error,
                },
            )

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
