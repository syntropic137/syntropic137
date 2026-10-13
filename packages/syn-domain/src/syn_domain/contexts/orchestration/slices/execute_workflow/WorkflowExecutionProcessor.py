"""WorkflowExecutionProcessor — reads to-do list, dispatches to handlers (ISS-196)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from syn_domain.contexts.orchestration._shared.shipped_ledger import ShippedLedgerProvider
from syn_domain.contexts.orchestration._shared.shipped_recorder import shipped_recorder
from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.domain.aggregate_execution.start_pins import (
    phase_definitions_of,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,
    ExecutionStatus,
    PhaseResult,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    CancelExecutionCommand,
    StartExecutionCommand,
    StartResumeCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.agent_attempts import (
    run_phase_agent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
    UnfinishedPhase,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.busy_upstream import (
    UpstreamRetryPolicy,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.cancel_teardown import (
    record_cancel_and_release,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.cancelled_work_record import (
    CancelledWorkLedger,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    SavedWork,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
    ExecutionJournal,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.failure_teardown import (
    record_failure_and_release,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
    AgentExecutionHandler,
    AgentExecutionResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_conversation import (
    record_phase_conversation,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_cost_limit import (
    raise_if_stopped_on_cost,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_delegation import (
    completion_failure,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_outcome import (
    completed_execution,
    completed_phase,
    failed_phase_outcome,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_push import push_recorder
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_retry import (
    retry_lost_terminal_attempt,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_runtime import (
    PhaseRuntimes,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_workspace import (
    PhaseWorkspace,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    # Imported at RUNTIME on purpose, not annotation-only: this module re-exports
    # it, and `slices/execute_workflow/__init__.py` plus a dozen tests do
    # `from ...WorkflowExecutionProcessor import WorkflowExecutionResult`. Moving
    # it into the type-checking block below would break every one of them at
    # import time, which is why TC001 is silenced here rather than obeyed.
    WorkflowExecutionResult,  # noqa: TC001
)
from syn_domain.contexts.orchestration.slices.execute_workflow.pull_request_observation import (
    with_open_pull_requests,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.resume_handoff import (
    inherited_outputs,
    inherited_phase_ids,
    record_continuation,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.shutdown_interruption import (
    preserve_interrupted_run,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.unpushed_work_guard import (
    already_saved_by_the_completion_gate,
    quarantined_records,
    refuse_to_complete_unsaved_phase,
)

if TYPE_CHECKING:
    from event_sourcing import ProjectionStore

    from syn_adapters.control import ExecutionController
    from syn_adapters.conversations import ConversationStoragePort
    from syn_adapters.workspace_backends.agentic.session_capture_service import (
        SessionCapturePort,
    )
    from syn_adapters.workspace_backends.service import WorkspaceService
    from syn_domain.contexts._shared.maintenance import AdmissionTicket
    from syn_domain.contexts._shared.repository_ref import RepositoryRef
    from syn_domain.contexts.agent_sessions.delegate_usage import SessionStorePort
    from syn_domain.contexts.agent_sessions.import_ledger import ImportLedgerPort
    from syn_domain.contexts.artifacts.domain.services.artifact_query_service import (
        ArtifactQueryServiceProtocol,
    )
    from syn_domain.contexts.artifacts.ports import (
        ArtifactContentStoragePort,
    )
    from syn_domain.contexts.orchestration._shared.eval_choice import LaunchEval
    from syn_domain.contexts.orchestration._shared.shipped_ledger import ShippedLedger
    from syn_domain.contexts.orchestration._shared.tags import TagSet
    from syn_domain.contexts.orchestration.domain.aggregate_execution.start_pins import (
        ResumeOrigin,
        SourceCommit,
    )
    from syn_domain.contexts.orchestration.ports import DelegationEvidencePort
    from syn_domain.contexts.orchestration.ports.RemoteBranchPort import RemoteBranchPort
    from syn_domain.contexts.orchestration.slices.execute_workflow.errors import ObservedBranches
    from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
        ObservabilityRecorder,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
        ClaudePluginMaterializerProtocol,
        SkillMaterializerProtocol,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.phase_runtime import (
        PhaseLaunch,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
        AgentHandlerProtocol,
        ArtifactRepository,
        CommandBuilder,
        ExecutionRepository,
        PhaseOutputCache,
        PromptBuilder,
        SessionRepository,
        TodoProjection,
    )

logger = logging.getLogger(__name__)


@dataclass
class _DispatchContext:
    """Execution-local dispatch state, created per run().

    D3 fix (stress 2026-06-10), hardened for concurrent dispatch: tracks
    the phase currently being dispatched so a workflow-level failure can
    mark the inner phase record as ``failed`` instead of stranding it at
    ``running``. Carried as a per-run object (not processor instance
    state) because BackgroundWorkflowDispatcher shares one processor
    across up to max_concurrent executions; instance state would let a
    concurrent execution overwrite the value and _fail_execution would
    emit a failed_phase_id belonging to a different execution.
    """

    current_phase_id: str | None = None
    #: What was taken out of the failing phase's workspace before it was torn
    #: down (#1321). Per-run for the same reason `current_phase_id` is: the
    #: processor is shared across concurrent executions, so instance state
    #: would attribute one run's artifacts to another's failure.
    kept_artifact_ids: list[str] = field(default_factory=list)
    #: What this run was asked to do, as `run()` was given it. Here rather than
    #: on the processor (where it was, as `self._inputs`, until #1311) for the
    #: third instance of the same reason: `run()` assigned it and
    #: `_provision_workspace` read it several awaits later, so a concurrent run
    #: starting in between replaced it and the next phase to provision built
    #: its prompt from the OTHER run's inputs - the issue, the repo and the PR
    #: number an agent is told to work on. Nothing downstream could detect it:
    #: a prompt is valid whichever run's inputs it names.
    inputs: dict[str, Any] = field(default_factory=dict)


class WorkflowExecutionProcessor:
    """Reads the to-do list and dispatches to handlers. Zero business logic."""

    def __init__(
        self,
        execution_repository: ExecutionRepository,
        session_repository: SessionRepository,
        workspace_service: WorkspaceService,
        artifact_repository: ArtifactRepository,
        artifact_content_storage: ArtifactContentStoragePort | None,
        artifact_query: ArtifactQueryServiceProtocol | None,
        conversation_storage: ConversationStoragePort | None,
        observability_writer: ObservabilityRecorder | None,
        controller: ExecutionController | None,
        prompt_builder: PromptBuilder,
        command_builder: CommandBuilder,
        todo_projection: TodoProjection | None = None,
        agent_handler: AgentHandlerProtocol | None = None,
        claude_plugin_materializer: ClaudePluginMaterializerProtocol | None = None,
        skill_materializer: SkillMaterializerProtocol | None = None,
        session_capture: SessionCapturePort | None = None,
        session_store: SessionStorePort | None = None,
        import_ledger: ImportLedgerPort | None = None,
        retry_policy: UpstreamRetryPolicy | None = None,
        remote_branches: RemoteBranchPort | None = None,
        owed_cancelled_work: ProjectionStore | None = None,
        delegation_evidence: DelegationEvidencePort | None = None,
        interrupt_budget_seconds: float = 60.0,
        shipped_ledger: ShippedLedger | None = None,
    ) -> None:
        #: Where what each phase shipped is recorded, once, as its stream is read:
        #: given, else kept by the Lane 2 store itself when it can (ShippedLedgerProvider).
        self._shipped_ledger = shipped_ledger or (
            observability_writer.shipped_ledger
            if isinstance(observability_writer, ShippedLedgerProvider)
            else None
        )
        #: How long a shutdown waits for a run's work to be saved and the run
        #: recorded INTERRUPTED before tearing it down (#1381).
        self._interrupt_budget_seconds = interrupt_budget_seconds
        self._session_repo = session_repository
        #: Read as a phase that declared delegation completes, to show its
        #: delegate actually ran (#894). See `phase_delegation`.
        self._delegation_evidence = delegation_evidence
        # How a phase answers a provider that is simply busy (#1303). Injected
        # only so a test can collapse the backoff to zero; production takes the
        # policy's own numbers and no caller chooses them.
        self._retry_policy = retry_policy or UpstreamRetryPolicy()
        #: Asked, as a phase fails, which PR is open from each branch it left,
        #: so a resume continues that PR and no other (#1513).
        self._remote_branches = remote_branches
        self._workspace_service = workspace_service
        self._artifact_repo = artifact_repository
        self._artifact_content_storage = artifact_content_storage
        self._artifact_query = artifact_query
        self._conversation_storage = conversation_storage
        self._observability_writer = observability_writer
        self._controller = controller
        self._prompt_builder = prompt_builder
        self._command_builder = command_builder
        assert todo_projection is not None, "todo_projection is required"
        self._todo_projection: TodoProjection = todo_projection
        self._journal = ExecutionJournal(execution_repository, todo_projection)
        #: Records what a cancel landed, owing it when refused; every run settles first (#1547).
        self._cancelled_work = CancelledWorkLedger(self._journal, owed_cancelled_work)
        self._agent_handler = agent_handler  # None → create fresh AgentExecutionHandler per call
        # WHY (issue #726, PR2): the materializer is the optional collaborator
        # that turns ResolvedClaudePlugin entries on the phase into workspace
        # files. Wired through to ``WorkspaceProvisionHandler`` per call.
        self._claude_plugin_materializer = claude_plugin_materializer
        # WHY (#772): mirrors claude_plugin_materializer above but for skills; handler hard-fails (no silent skip) on unmatched skills
        self._skill_materializer = skill_materializer
        # Infrastructure state (not domain state — ephemeral). One object per
        # RUN, not thirteen maps and not one object for the whole processor:
        # see `phase_runtime` for why the maps are only ever correct together,
        # why this processor should not know they are maps at all, and why one
        # shared set of them let concurrent runs of a workflow take each
        # other's workspaces (#1311).
        self._runtimes = PhaseRuntimes(
            capture_port=session_capture,
            session_store=session_store,
            writer=observability_writer,
            ledger=import_ledger,
        )

    def _workspaces_for(
        self,
        execution_id: str,
        inputs: dict[str, Any],
    ) -> PhaseWorkspace:
        """The storage seam of a phase: provision it, claim what it produced.

        Dispatching to it is a dispatch decision; how any of it is built is
        not, so the building moved to `phase_workspace` (#1367).

        Built per access, NOT once in `__init__`, because the collaborators it
        needs are replaceable on the processor after construction - the journal
        and the artifact repository are both swapped that way - and a seam that
        snapshotted them at construction would quietly keep using the originals.
        The handlers inside it were already constructed per call, so reading
        the current references here costs nothing the old code did not.
        """
        return PhaseWorkspace(
            session_repository=self._session_repo,
            workspace_service=self._workspace_service,
            artifact_repository=self._artifact_repo,
            artifact_content_storage=self._artifact_content_storage,
            artifact_query=self._artifact_query,
            observability_writer=self._observability_writer,
            prompt_builder=self._prompt_builder,
            command_builder=self._command_builder,
            claude_plugin_materializer=self._claude_plugin_materializer,
            skill_materializer=self._skill_materializer,
            runtime=self._runtimes.of(execution_id),
            journal=self._journal,
            inputs=inputs,
        )

    async def resolve_inheritance(self, origin: ResumeOrigin | None) -> None:
        """Raise unless a resume's inherited outputs can be handed over.

        For a caller that must find that out BEFORE dispatching the start rather
        than inside it: a refusal raised in the background task is reported
        after the record was already written `dispatched`, and a refusal known
        before the dispatch is cheaper and clearer. `start_resume` calls this through the processor it already holds,
        rather than importing `resume_handoff` - a slice may not import another
        slice's modules, and depending on an injected collaborator is the way
        across that boundary.
        """
        await inherited_outputs(self._artifact_query, origin)

    async def run(
        self,
        workflow_id: str,
        workflow_name: str,
        phases: list[ExecutablePhase],
        inputs: dict[str, Any],
        execution_id: str,
        repos: list[RepositoryRef] | None = None,
        expected_completion_at: datetime | None = None,
        admitted: AdmissionTicket | None = None,
        source_commits: list[SourceCommit] | None = None,
        tags: TagSet | None = None,
        launch_eval: LaunchEval | None = None,
        workflow_version: str | None = None,
    ) -> WorkflowExecutionResult:
        """Execute a workflow using the Processor To-Do List pattern.

        ``admitted`` is the admission lease this execution was started under
        (#1387), and it ends a few lines below, at the moment the start event
        is durable. Nowhere earlier would be true: everything between the
        admission decision and that write is queueing, and a deploy that
        drained over it would count a quiet system and then kill this run.
        """
        # PromptBuilder reads ``inputs["repos"]`` for ``{{repos}}`` template substitution.
        # ADR-063: write the canonical HTTPS form of typed RepositoryRef so the prompt
        # never sees un-normalized slugs. TODO(#712): replace this with typed access
        # once PromptBuilder consumes ``RepositoryRef`` directly.
        if repos and "repos" not in inputs:
            inputs["repos"] = ",".join(r.https_url for r in repos)
        aggregate = WorkflowExecutionAggregate()
        start_cmd = StartExecutionCommand(
            execution_id=execution_id,
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            total_phases=len(phases),
            inputs=inputs,
            expected_completion_at=expected_completion_at,
            phase_definitions=phase_definitions_of(phases),
            pinned_phases=phases,
            source_commits=source_commits,
            tags=tags,
            launch_eval=launch_eval,
            workflow_version=workflow_version,
        )
        aggregate.start_execution(start_cmd)
        return await self._run_started(aggregate, workflow_id, phases, inputs, repos, admitted)

    async def run_resume(
        self,
        command: StartResumeCommand,
        repos: list[RepositoryRef] | None = None,
        admitted: AdmissionTicket | None = None,
    ) -> WorkflowExecutionResult:
        """Start and run the resume a parent admitted (ADR-014 s7).

        The same drain as `run`, over the parent's PINNED phases (#1454) and
        from the resume phase on: the aggregate and the to-do list both start
        the child with its inherited phases complete, and their outputs are
        handed forward from the parent's artifacts.
        """
        aggregate = WorkflowExecutionAggregate()
        aggregate.start_resume(command)
        return await self._run_started(
            aggregate,
            command.workflow_id,
            command.pinned_phases,
            dict(command.inputs),
            repos,
            admitted,
            origin=command.resumed_from,
        )

    async def _run_started(
        self,
        aggregate: WorkflowExecutionAggregate,
        workflow_id: str,
        phases: list[ExecutablePhase],
        inputs: dict[str, Any],
        repos: list[RepositoryRef] | None,
        admitted: AdmissionTicket | None,
        origin: ResumeOrigin | None = None,
    ) -> WorkflowExecutionResult:
        """Record the start, then drain the to-do list until the run ends."""
        await self._cancelled_work.settle()
        started_at = datetime.now(UTC)
        execution_id = aggregate.id or ""
        phase_map = {p.phase_id: p for p in phases}
        # Before the stream opens: a resume whose inheritance cannot be read
        # must not leave a child that exists and can never run its first phase.
        phase_outputs = await inherited_outputs(self._artifact_query, origin)
        record_continuation(phase_outputs, aggregate.start_pins)
        # #1387: durable, therefore visible. From the write the drain counts
        # this execution and a maintenance transition may proceed over it;
        # before it, it existed only as a queued task, and `set_mode(active=True)`
        # was waiting on this line. #1707: the write is also where whoever
        # queued it learns it started - not later, where an exception would
        # read as a start that never happened. If `open()` raised before the
        # write - a duplicate stream, a store that is down - the lease is
        # ended by the worker instead, which is the other honest answer:
        # nothing started.
        await self._journal.open(
            aggregate, written=admitted.mark_durable if admitted is not None else None
        )

        phase_results: list[PhaseResult] = []
        all_artifact_ids: list[str] = []
        completed_phase_ids = inherited_phase_ids(origin)
        dispatch_ctx = _DispatchContext(inputs=inputs)

        try:
            await self._drain_todo_list(
                execution_id=execution_id,
                aggregate=aggregate,
                phase_map=phase_map,
                phase_results=phase_results,
                all_artifact_ids=all_artifact_ids,
                completed_phase_ids=completed_phase_ids,
                phase_outputs=phase_outputs,
                repos=repos,
                dispatch_ctx=dispatch_ctx,
            )
            if aggregate.status == ExecutionStatus.CANCELLED:
                # What the interrupted phase wrote or said, kept before the
                # cancel tears its workspace down (#1476).
                all_artifact_ids.extend(
                    i for i in dispatch_ctx.kept_artifact_ids if i not in all_artifact_ids
                )
                return await record_cancel_and_release(
                    aggregate=aggregate,
                    runtime=self._runtimes.of(execution_id),
                    workspaces=self._workspaces_for(execution_id, {}),
                    ledger=self._cancelled_work,
                    execution_id=execution_id,
                    workflow_id=workflow_id,
                    phase_results=phase_results,
                    all_artifact_ids=all_artifact_ids,
                    started_at=started_at,
                    cancel_reason=aggregate.cancel_reason,
                    phase_id=dispatch_ctx.current_phase_id,
                )
            return await self._complete_execution(
                aggregate,
                execution_id,
                workflow_id,
                phases,
                phase_results,
                all_artifact_ids,
                started_at,
            )
        except Exception as e:
            logger.exception(
                "Workflow execution failed (exec=%s, workflow=%s): %s",
                execution_id,
                workflow_id,
                e,
            )
            return await self._fail_execution(
                e,
                aggregate,
                execution_id,
                workflow_id,
                phases,
                phase_results,
                all_artifact_ids,
                completed_phase_ids,
                started_at,
                failed_phase_id=dispatch_ctx.current_phase_id,
                kept_artifact_ids=dispatch_ctx.kept_artifact_ids,
            )
        except asyncio.CancelledError:
            # Platform shutdown (#1381): neither path above saves the work on a
            # cancel, so save it and record the run INTERRUPTED before the
            # teardown below, then let the cancel go on.
            await preserve_interrupted_run(
                aggregate=aggregate,
                runtime=self._runtimes.of(execution_id),
                workspaces=self._workspaces_for(execution_id, {}),
                journal=self._journal,
                workflow_id=workflow_id,
                execution_id=execution_id,
                phase_id=dispatch_ctx.current_phase_id,
                kept_artifact_ids=dispatch_ctx.kept_artifact_ids,
                budget_seconds=self._interrupt_budget_seconds,
            )
            raise
        finally:
            # A shutdown may cancel the minutes-long agent await before either
            # terminal path runs. Tear down only this execution's runtime,
            # then release its registry entry on every way out (#1311, #1319).
            try:
                await self._runtimes.of(execution_id).abandon_all("shutdown")
            finally:
                self._runtimes.release(execution_id)

    async def _drain_todo_list(
        self,
        execution_id: str,
        aggregate: WorkflowExecutionAggregate,
        phase_map: dict[str, ExecutablePhase],
        phase_results: list[PhaseResult],
        all_artifact_ids: list[str],
        completed_phase_ids: list[str],
        phase_outputs: PhaseOutputCache,
        repos: list[RepositoryRef] | None,
        dispatch_ctx: _DispatchContext,
    ) -> None:
        """Process to-do items until the list is empty (all phases done or cancelled)."""
        while True:
            todos = await self._todo_projection.get_pending(execution_id)
            if not todos:
                break
            await self._dispatch(
                todo=todos[0],
                aggregate=aggregate,
                phase_map=phase_map,
                phase_results=phase_results,
                all_artifact_ids=all_artifact_ids,
                completed_phase_ids=completed_phase_ids,
                phase_outputs=phase_outputs,
                repos=repos,
                dispatch_ctx=dispatch_ctx,
            )

    async def _dispatch(
        self,
        todo: TodoItem,
        aggregate: WorkflowExecutionAggregate,
        phase_map: dict[str, ExecutablePhase],
        phase_results: list[PhaseResult],
        all_artifact_ids: list[str],
        completed_phase_ids: list[str],
        phase_outputs: PhaseOutputCache,
        repos: list[RepositoryRef] | None,
        dispatch_ctx: _DispatchContext,
    ) -> None:
        """Dispatch a single to-do item to its handler."""
        assert todo.phase_id is not None
        phase = phase_map[todo.phase_id]
        # D3 (stress 2026-06-10): record the phase under dispatch so
        # _fail_execution can attribute a workflow-level failure to a
        # real phase id and unstrand the inner phase record. Stored on
        # the per-run _DispatchContext, never on the shared processor.
        dispatch_ctx.current_phase_id = todo.phase_id
        if todo.action == TodoAction.PROVISION_WORKSPACE:
            await self._workspaces_for(todo.execution_id, dispatch_ctx.inputs).start_phase(
                todo,
                phase,
                aggregate,
                repos,
                completed_phase_ids,
                phase_outputs,
            )
        elif todo.action == TodoAction.RUN_AGENT:
            await self._handle_run_agent(todo, phase, aggregate, dispatch_ctx)
        elif todo.action == TodoAction.COLLECT_ARTIFACTS:
            await self._workspaces_for(todo.execution_id, dispatch_ctx.inputs).collect(
                todo,
                phase,
                aggregate,
                all_artifact_ids,
                phase_outputs,
            )
        elif todo.action == TodoAction.COMPLETE_PHASE:
            await self._handle_complete_phase(
                todo, phase, aggregate, phase_results, completed_phase_ids
            )
            # The phase finished cleanly; a later workflow-level failure
            # (between phases) must not be attributed to it.
            dispatch_ctx.current_phase_id = None

    async def _complete_execution(
        self,
        aggregate: WorkflowExecutionAggregate,
        execution_id: str,
        workflow_id: str,
        phases: list[ExecutablePhase],
        phase_results: list[PhaseResult],
        all_artifact_ids: list[str],
        started_at: datetime,
    ) -> WorkflowExecutionResult:
        """Build completion command, save, and return success result."""
        completion = completed_execution(phase_results, all_artifact_ids)
        aggregate.complete_execution(completion.as_command(execution_id, total_phases=len(phases)))
        await self._journal.append(aggregate)
        return completion.execution_result(workflow_id, execution_id, started_at=started_at)

    async def _observe_branches(
        self, observed: ObservedBranches | None, aggregate: WorkflowExecutionAggregate
    ) -> ObservedBranches | None:
        """The failing phase's branches, with the PR open from each when a forge is wired (#1513)."""
        if self._remote_branches is None:
            return observed
        repositories = [c.repository for c in aggregate.start_pins.source_commits]
        return await with_open_pull_requests(observed, self._remote_branches, repositories)

    async def _fail_execution(
        self,
        error: Exception,
        aggregate: WorkflowExecutionAggregate,
        execution_id: str,
        workflow_id: str,
        phases: list[ExecutablePhase],
        phase_results: list[PhaseResult],
        all_artifact_ids: list[str],
        completed_phase_ids: list[str],
        started_at: datetime,
        failed_phase_id: str | None = None,
        kept_artifact_ids: list[str] | None = None,
    ) -> WorkflowExecutionResult:
        """Close open sessions, save failure event, and return failed result.

        ``failed_phase_id`` comes from the run's own _DispatchContext so
        it always belongs to THIS execution, even with concurrent runs
        sharing the processor instance. ``kept_artifact_ids`` comes from the
        same place and for the same reason: it is what was taken out of that
        phase's workspace on the way here (#1321), and it has to reach the
        execution's own artifact list, the failed phase's record and the
        event - otherwise the artifact exists and nothing points at it.
        """
        kept = list(kept_artifact_ids or [])
        for artifact_id in kept:
            if artifact_id not in all_artifact_ids:
                all_artifact_ids.append(artifact_id)
        # BEFORE any await: teardown clears both maps, so reading them
        # afterwards timed the phase to the end of cleanup and lost the
        # session_id entirely (#1036).
        runtime = self._runtimes.of(execution_id)
        timings = runtime.timings()
        # Read in the same breath as the timings, and for the same reason: the
        # counts are the dying phase's own, and this is the last frame in which
        # anything can still ask for them (#1262). Without this the phase
        # reported zero tokens no matter what it had burned, so an exit 124
        # after 735 tokens - a stall - was indistinguishable from one after
        # 300k, which needed a bigger budget rather than a retry.
        #
        # Asked with `execution_id`, not just the phase: this processor is
        # shared across concurrent dispatches and two runs of one workflow have
        # the same phase ids, so "what did `implement` spend" names two answers.
        # The id is the run's own, so it always names this one's.
        usage = runtime.usage_for(execution_id, failed_phase_id)
        # Before the teardown below, the only window in which either is
        # possible: SAVE what would die with the container (#1231), then read
        # where that leaves the branches (#1200). Saving first is what lets the
        # branch report point at a quarantine ref instead of at nothing.
        #
        # This does not make the phase succeed and must not be read as doing
        # so. `error` is untouched, `failed_phase_outcome` appends to its reason
        # rather than replacing it, and the aggregate is still told the
        # execution failed: a phase killed at its timeout_seconds is still a
        # phase that ran out of time. What changes is only that the time is now
        # the whole of what the timeout costs.
        #
        # The one failure that arrives with the workspace already emptied is
        # the completion gate's own refusal, which quarantined before it raised
        # (#1184). Saving again would push a second, differently-timestamped
        # commit to the same ref, be rejected as a non-fast-forward, and report
        # the work as lost directly under the gate's report that it is not.
        saved = (
            SavedWork()
            if already_saved_by_the_completion_gate(error)
            else await runtime.save_unpushed_work(failed_phase_id, execution_id=execution_id)
        )
        # Whichever of the two saved it, the workflow changes a rescue had to
        # leave out are stored now, while the run still knows them, and
        # pointed at from the failed phase like everything else it kept (#1437).
        records = quarantined_records(error, saved)
        for artifact_id in await self._workspaces_for(execution_id, {}).keep_dropped_workflows(
            records,
            workflow_id=workflow_id,
            phase_id=failed_phase_id,
            execution_id=execution_id,
            session_id=timings.session_ids.get(failed_phase_id or "", ""),
        ):
            kept.append(artifact_id)
            if artifact_id not in all_artifact_ids:
                all_artifact_ids.append(artifact_id)
        observed = await self._observe_branches(await runtime.observe(failed_phase_id), aggregate)
        failure = failed_phase_outcome(
            error,
            failed_phase_id,
            timings.started_at,
            timings.session_ids,
            observed=observed,
            kept_artifact_ids=kept,
            usage=usage,
            saved=saved,
            quarantined=records,
            repositories=[c.repository for c in aggregate.start_pins.source_commits],
        )
        if failure.result is not None:
            phase_results.append(failure.result)

        await record_failure_and_release(
            failure,
            aggregate=aggregate,
            journal=self._journal,
            runtime=runtime,
            execution_id=execution_id,
            completed_phases=len(completed_phase_ids),
            total_phases=len(phases),
        )
        return failure.execution_result(
            workflow_id,
            execution_id,
            started_at=started_at,
            phase_results=phase_results,
            artifact_ids=all_artifact_ids,
        )

    def _get_agent_handler(self) -> AgentHandlerProtocol:
        """Return the injected handler, or create a fresh real one (default behaviour)."""
        if self._agent_handler is not None:
            return self._agent_handler
        return AgentExecutionHandler(controller=self._controller)

    async def _handle_run_agent(
        self,
        todo: TodoItem,
        phase: ExecutablePhase,
        aggregate: WorkflowExecutionAggregate,
        dispatch_ctx: _DispatchContext,
    ) -> None:
        """Dispatch RUN_AGENT."""
        assert todo.phase_id is not None
        session_id = todo.session_id or ""
        runtime = self._runtimes.of(todo.execution_id)
        launch = runtime.launch(todo.phase_id, session_id=session_id)
        workflow_id = aggregate.workflow_id or ""

        # EVERY WAY OUT OF HERE THAT ENDS THE RUN GOES PAST THE SAME DOOR
        # (#1321, #1476). Each exit below either completes the phase, retries
        # it, or unwinds to `_cancel_execution` / `_fail_execution`, which
        # abandon the workspace - so whatever the phase wrote under
        # artifacts/output/, or only said, is destroyed with it unless it is
        # kept here first, because COLLECT_ARTIFACTS is a LATER to-do item that
        # is now never dispatched. That cost exec-76a6d3b22b23 a finished
        # 1322-line deliverable and exec-82ce478a6c46 a drafted review.
        #
        # "This phase did not complete" and "throw away what it produced" are
        # different decisions and this is where they come apart. The keep is
        # attached to the exception rather than repeated at each raise so that
        # a raise added later cannot forget it, and it never raises itself, so
        # the reason the phase failed always reaches the caller intact. The
        # `try` starts before the agent runs so a raise from the run itself or
        # from recording it is covered too.
        said: str | None = None
        kept = False
        try:
            # A BUSY UPSTREAM IS NOT A FAILED PHASE (#1303). Everything below
            # treats the result as final, and for every cause but one it is;
            # `run_phase_agent` is what makes that true, by not returning until
            # there is no further attempt to come.
            result = await run_phase_agent(
                handler=self._get_agent_handler(),
                todo=todo,
                phase=phase,
                launch=launch,
                session_id=session_id,
                observability=self._observability_writer,
                retry_policy=self._retry_policy,
                on_push=push_recorder(aggregate, self._journal, todo.phase_id),
                shipped=shipped_recorder(self._shipped_ledger, aggregate, todo.execution_id),
            )
            said = result.stream_result.last_agent_message

            runtime.remember_leader(
                todo.phase_id, execution_id=todo.execution_id, stream_result=result.stream_result
            )
            await record_phase_conversation(
                self._conversation_storage,
                result,
                session_id=session_id,
                execution_id=todo.execution_id,
                phase_id=todo.phase_id,
                workflow_id=workflow_id,
                requested_model=phase.agent_config.model,
                started_at=launch.started_at,
            )
            runtime.record_agent_run(todo.phase_id, execution_id=todo.execution_id, result=result)

            # BEFORE the cancel branch: a cost stop is also an interrupt, but
            # nobody cancelled anything. Raised, so it reaches the aggregate as
            # a failed phase - resumable, like one killed at its timeout -
            # through the same path that keeps what the phase wrote (#1376).
            raise_if_stopped_on_cost(todo.phase_id, result.stream_result.cost_limit_reason)

            if result.stream_result.interrupt_requested:
                kept = True
                await self._keep(
                    todo,
                    phase,
                    launch,
                    workflow_id,
                    dispatch_ctx,
                    said,
                    UnfinishedPhase.INTERRUPTED,
                )
                await self._handle_cancel_signal(todo, result, aggregate)
                return

            command = result.command
            assert command is not None, "a non-cancelled run must carry its completion command"
            # THE PHASE'S OWN REPORT, on the same footing as its exit status
            # and checked before the aggregate is told the run completed
            # (#1256). WHICH channel ended the run, and what the failure is
            # counted as, are `agent_run_outcome`'s to decide (#1367).
            failure = await completion_failure(
                result,
                phase_id=todo.phase_id,
                evidence=self._delegation_evidence,
                workspace=runtime.workspace_for(todo.phase_id),
                required_delegate=phase.agent_config.required_delegate,
                requires_verdict=phase.requires_verdict,
            )
            if failure is not None:
                logger.error(str(failure))
                # A retried attempt keeps nothing: the phase is not over, and
                # the attempt that completes it produces the phase's artifact.
                if await retry_lost_terminal_attempt(
                    todo,
                    aggregate,
                    runtime,
                    self._journal,
                    reason=result.stream_result.error_reason,
                    failure=str(failure),
                ):
                    return
                raise failure

            aggregate.agent_execution_completed(command)
            await self._journal.append(aggregate)
        except Exception:
            if not kept:
                await self._keep(
                    todo, phase, launch, workflow_id, dispatch_ctx, said, UnfinishedPhase.FAILED
                )
            raise

    async def _keep(
        self,
        todo: TodoItem,
        phase: ExecutablePhase,
        launch: PhaseLaunch,
        workflow_id: str,
        dispatch_ctx: _DispatchContext,
        said: str | None,
        outcome: UnfinishedPhase,
    ) -> None:
        """Keep what an unfinished phase wrote or said, before its workspace goes."""
        dispatch_ctx.kept_artifact_ids = await self._workspaces_for(
            todo.execution_id, dispatch_ctx.inputs
        ).keep_unfinished_output(
            todo,
            phase,
            workspace=launch.workspace,
            workflow_id=workflow_id,
            last_agent_message=said,
            outcome=outcome,
        )

    async def _handle_cancel_signal(
        self,
        todo: TodoItem,
        result: AgentExecutionResult,
        aggregate: WorkflowExecutionAggregate,
    ) -> None:
        """Dispatch CancelExecutionCommand when the agent stream was interrupted by a cancel signal."""
        assert todo.phase_id is not None, "phase_id must be set for a running agent todo"
        cancel_cmd = CancelExecutionCommand(
            execution_id=todo.execution_id,
            phase_id=todo.phase_id,
            reason=result.stream_result.interrupt_reason or "Cancelled by user",
        )
        aggregate.cancel_execution(cancel_cmd)
        await self._journal.append(aggregate)

    async def _handle_complete_phase(
        self,
        todo: TodoItem,
        phase: ExecutablePhase,
        aggregate: WorkflowExecutionAggregate,
        phase_results: list[PhaseResult],
        completed_phase_ids: list[str],
    ) -> None:
        """Dispatch COMPLETE_PHASE.

        THE ORDER OF THE FOUR STEPS BELOW IS THE GUARANTEE (#1184). The guard
        runs before the phase gives anything up, before the aggregate is told
        it succeeded, before that is persisted, and before the runtime tears
        the workspace down. Every one of those is a point of no return, and the
        guard is only a guard on the near side of all four.

        `phase` is here for the guard, which cannot tell an authored edit from
        a build tool's side effect without the phase's own declaration (#1308).
        Every other handler already took it; this one dropped it, which is why
        the declaration had nowhere to arrive.
        """
        assert todo.phase_id is not None
        runtime = self._runtimes.of(todo.execution_id)
        # FIRST, and on the real path rather than inside a try: nothing has
        # been popped, the workspace is still alive and the aggregate has not
        # been told this phase succeeded, so the raise IS the outcome (#1184).
        await refuse_to_complete_unsaved_phase(
            runtime.live_workspaces,
            todo,
            delivers_repo_changes=phase.delivers_repo_changes,
        )

        harvest = runtime.harvest(todo.execution_id, todo.phase_id)
        outcome = completed_phase(
            execution_id=todo.execution_id,
            workflow_id=aggregate.workflow_id or "",
            phase_id=todo.phase_id,
            session_id=todo.session_id,
            started_at=harvest.started_at,
            artifact_ids=harvest.artifact_ids,
            auth_tokens=harvest.auth_tokens,
        )
        phase_results.append(outcome.result)
        completed_phase_ids.append(todo.phase_id)

        aggregate.complete_phase(outcome.command)
        await self._journal.append(aggregate)

        await runtime.finalize(
            todo.phase_id,
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            cache_creation_tokens=outcome.cache_creation_tokens,
            cache_read_tokens=outcome.cache_read_tokens,
            total_tokens=outcome.total_tokens,
            duration_seconds=outcome.duration_seconds,
        )
