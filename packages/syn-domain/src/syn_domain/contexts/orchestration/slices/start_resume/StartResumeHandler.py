"""Start the child execution a parent's resume admitted (ADR-014 s7, #1454).

The parent's `ExecutionResumed` is the decision; this carries it out. Every
fact the child runs with is read from the PARENT's stream - its pinned phases,
its inputs, its recorded commits and the inherited prefix the decision fixed -
and nothing from the workflow template, which may have been edited since the
parent started. The aggregate builds the command and refuses a start that does
not match its snapshot; this handler only loads, asks and hands over.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from event_sourcing import StreamAlreadyExistsError

from syn_domain.contexts._shared.maintenance import refuse_if_paused
from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_domain.contexts.orchestration.domain.aggregate_execution.resume_start import (
    refuse_resume_start,
)
from syn_domain.contexts.orchestration.slices.start_resume.value_objects import ResumeChild

if TYPE_CHECKING:
    from syn_domain.contexts._shared.maintenance import AdmissionTicket, MaintenancePort
    from syn_domain.contexts.orchestration._shared.template_launch import TemplateLaunches
    from syn_domain.contexts.orchestration.domain.aggregate_execution.branch_continuation import (
        RemoteBranchReading,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
        StartResumeCommand,
    )
    from syn_domain.contexts.orchestration.ports.RemoteBranchPort import RemoteBranchPort
    from syn_domain.contexts.orchestration.ports.WorkflowExecutionRepositoryPort import (
        WorkflowExecutionRepositoryPort,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
        WorkflowExecutionProcessor,
        WorkflowExecutionResult,
    )

logger = logging.getLogger(__name__)


class StartResumeHandler:
    """Loads a resumed parent and runs the child it admitted.

    Idempotent, as an infrastructure handler must be: a child whose stream
    already exists has started, and asking again returns None rather than
    starting it twice. The stream's NoStream write is what makes that true
    when two callers race; the lookup first only spares the common case the
    work of building a start that would be refused.
    """

    def __init__(
        self,
        processor: WorkflowExecutionProcessor,
        execution_repository: WorkflowExecutionRepositoryPort,
        maintenance: MaintenancePort | None = None,
        remote_branches: RemoteBranchPort | None = None,
        launches: TemplateLaunches | None = None,
    ) -> None:
        self._processor = processor
        self._executions = execution_repository
        #: Asks the forge whether the parent's pushed branches are still where
        #: it left them (#1513). Without one, nothing can be verified, and every
        #: candidate is abandoned with that reason rather than reused blind.
        self._remote_branches = remote_branches
        # Optional for the same reason as on ExecuteWorkflowHandler (#1387):
        # a fixture admits nothing. Production passes it.
        self._maintenance = maintenance
        # #1588: a resumed child is a launch of its template like any other,
        # so archive must see it before the child's stream exists.
        self._launches = launches

    async def handle(
        self,
        parent_execution_id: str,
        *,
        admitted: AdmissionTicket | None = None,
    ) -> WorkflowExecutionResult | None:
        """Run the child of ``parent_execution_id``; None if it already started.

        Raises when the parent does not exist, has admitted no resume, or has a
        snapshot the child may not start from (`resume_start.refuse_resume_start`).
        """
        # #1387 backstop, as in ExecuteWorkflowHandler: skipped for a ticketed
        # start, whose admission the gate already decided under its lock.
        if admitted is None and self._maintenance is not None:
            await refuse_if_paused(self._maintenance)

        command = await self._command_for(parent_execution_id)
        if await self._executions.get_by_id(command.aggregate_id) is not None:
            logger.info(
                "Resume %s of %s already started", command.aggregate_id, parent_execution_id
            )
            return None

        # The repositories the PARENT ran against, as it recorded them - not
        # the template's list, which may have changed. Which commit each is
        # checked out at is the child's own start pins' answer, read where the
        # workspace is provisioned (`StartPins.checkout_commits`, #1458).
        repos = [RepositoryRef.from_slug(c.repository) for c in command.source_commits]
        # The facts the aggregate decides continuation from (#1513): where each
        # branch the parent's failing phase pushed is NOW. Read here, at the
        # start, so a branch deleted or force-pushed since is abandoned with a
        # recorded reason instead of reused stale.
        command.remote_branches = await self._read_remote_branches(command)
        # #1588: on the template's stream before the child's own stream exists,
        # as ExecuteWorkflowHandler does. Raises TemplateArchivedError if the
        # template was archived since the parent ran.
        if self._launches is not None:
            await self._launches.record(command.workflow_id, command.aggregate_id)
        try:
            return await self._processor.run_resume(command, repos=repos, admitted=admitted)
        except StreamAlreadyExistsError:
            logger.info(
                "Resume %s of %s already started", command.aggregate_id, parent_execution_id
            )
            return None

    async def validate(self, parent_execution_id: str) -> ResumeChild:
        """Raise now if the child of ``parent_execution_id`` could not start.

        For the dispatcher to call BEFORE it spawns the start (#1039's rule):
        once the start is a background task a refusal can reach nobody, and
        the to-do list would record as started a child that never was.

        Returns the child it would start, so the start can be queued under the
        child's own id and shown as `queued` while it waits (#1557).
        """
        command = await self._command_for(parent_execution_id)
        refusal = refuse_resume_start(command)
        if refusal is not None:
            raise ValueError(refusal)
        # The inheritance is resolved HERE, synchronously, for the reason in the
        # docstring above. `inherited_outputs` also runs inside the background
        # start, before the child's stream opens, and a raise there now reaches
        # the to-do list through the dispatcher's `on_failure` (#1463) - but only
        # after a task was spent and a start was queued for an execution-budget slot
        # (codex review of #1459). Resolving it here means a vanished artifact is
        # refused before anything is dispatched.
        await self._processor.resolve_inheritance(command.resumed_from)
        return ResumeChild(execution_id=command.aggregate_id, workflow_id=command.workflow_id)

    async def _read_remote_branches(self, command: StartResumeCommand) -> list[RemoteBranchReading]:
        """What the forge says about each branch the child could continue."""
        if self._remote_branches is None:
            return []
        return [
            await self._remote_branches.read_branch(c.repository, c.branch)
            for c in command.continuation_candidates
        ]

    async def _command_for(self, parent_execution_id: str) -> StartResumeCommand:
        parent = await self._executions.get_by_id(parent_execution_id)
        if parent is None:
            msg = f"Cannot start the resume of {parent_execution_id}: no such execution"
            raise ValueError(msg)
        return parent.resume_start_command()
