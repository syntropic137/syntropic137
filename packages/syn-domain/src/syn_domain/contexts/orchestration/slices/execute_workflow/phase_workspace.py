"""A phase's workspace: bring it up, and take out what it wrote.

WHY THE PROCESSOR SHOULD NOT KNOW ANY OF THIS. Its job is to read the to-do
list and dispatch, and a dispatch decision is "this phase needs a workspace"
or "this phase's output has to be claimed". None of the four things below is
that decision:

- provisioning means building a `WorkspaceProvisionHandler` out of two
  builders and two optional materializers, and handing it an
  `ArtifactCollector` so a phase can read what earlier phases produced;
- claiming output on the good path means an `ArtifactCollectionHandler` over
  that same collector, plus the salvage inputs (`last_agent_message` from the
  AGGREGATE, `describe_work` deferred) that only matter when the phase wrote
  nothing;
- claiming it on the bad path means the same collector again with
  `UnfinishedPhase.FAILED`, and the rule that it must never raise;
- and all four share one set of storage collaborators, which is the actual
  reason they belong together rather than beside the dispatch they serve.

Those change together whenever the storage seam changes, and never when the
to-do list gains an action. Extracted from `WorkflowExecutionProcessor` for
that reason (#1367).

WHAT THIS MODULE DELIBERATELY DOES NOT DO. It decides nothing about the
phase's outcome. `start_phase` issues the aggregate's own `StartPhaseCommand`
and `collect` its `artifacts_collected`, but the aggregate rules them; this
only carries the infrastructure result back. Whether a phase failed, and what
kind of failure it was, is `agent_run_outcome`'s question and is not asked
here - `keep_unfinished_output` runs for a phase that is ALREADY decided, and
its only question is what survives the teardown (#1321).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    StartPhaseCommand,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
    ArtifactCollector,
    UnfinishedPhase,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.ArtifactCollectionHandler import (
    ArtifactCollectionHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
    ProvisionResult,
    WorkspaceProvisionHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SessionLifecycleManager import (
    SessionLifecycleManager,
)

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.service import WorkspaceService
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts._shared.repository_ref import RepositoryRef
    from syn_domain.contexts.artifacts.domain.services.artifact_query_service import (
        ArtifactQueryServiceProtocol,
    )
    from syn_domain.contexts.artifacts.ports import ArtifactContentStoragePort
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoItem
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ExecutablePhase,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
        ObservabilityRecorder,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
        ExecutionJournal,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
        ClaudePluginMaterializerProtocol,
        SkillMaterializerProtocol,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.phase_runtime import PhaseRuntime
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
        ArtifactRepository,
        CommandBuilder,
        PhaseOutputCache,
        PromptBuilder,
        SessionRepository,
    )

logger = logging.getLogger(__name__)


class PhaseWorkspace:
    """The storage seam of a phase: provision it, and claim what it produced."""

    def __init__(
        self,
        *,
        session_repository: SessionRepository,
        workspace_service: WorkspaceService,
        artifact_repository: ArtifactRepository,
        artifact_content_storage: ArtifactContentStoragePort | None,
        artifact_query: ArtifactQueryServiceProtocol | None,
        observability_writer: ObservabilityRecorder | None,
        prompt_builder: PromptBuilder,
        command_builder: CommandBuilder,
        claude_plugin_materializer: ClaudePluginMaterializerProtocol | None,
        skill_materializer: SkillMaterializerProtocol | None,
        runtime: PhaseRuntime,
        journal: ExecutionJournal,
        inputs: dict[str, Any],
    ) -> None:
        self._session_repo = session_repository
        self._workspace_service = workspace_service
        self._artifact_repo = artifact_repository
        self._artifact_content_storage = artifact_content_storage
        self._artifact_query = artifact_query
        self._observability_writer = observability_writer
        self._prompt_builder = prompt_builder
        self._command_builder = command_builder
        self._claude_plugin_materializer = claude_plugin_materializer
        self._skill_materializer = skill_materializer
        self._runtime = runtime
        self._journal = journal
        #: The run's own inputs, read by `provision` for the prompt. Handed in
        #: per construction because the processor is shared across concurrent
        #: executions: this object is built against one run's collaborators and
        #: must not be able to see another run's inputs.
        self._inputs = inputs

    def _collector(self) -> ArtifactCollector:
        """One collector shape, built the same way for every path through here."""
        return ArtifactCollector(
            self._artifact_repo, self._artifact_content_storage, self._artifact_query
        )

    async def start_phase(
        self,
        todo: TodoItem,
        phase: ExecutablePhase,
        aggregate: WorkflowExecutionAggregate,
        repos: list[RepositoryRef] | None,
        completed_phase_ids: list[str],
        phase_outputs: PhaseOutputCache,
    ) -> None:
        """Dispatch PROVISION_WORKSPACE."""
        assert todo.phase_id is not None
        session_id = str(uuid4())
        start_cmd = StartPhaseCommand(
            execution_id=todo.execution_id,
            workflow_id=aggregate.workflow_id or "",
            phase_id=todo.phase_id,
            phase_name=phase.name,
            phase_order=phase.order,
            session_id=session_id,
        )
        aggregate.start_phase(start_cmd)

        session_mgr = SessionLifecycleManager(
            repository=self._session_repo,
            session_id=session_id,
            workflow_id=aggregate.workflow_id or "",
            execution_id=todo.execution_id,
            phase_id=todo.phase_id,
            agent_provider=phase.agent_config.provider,
            agent_model=phase.agent_config.model,
            repos=[r.slug for r in repos] if repos else [],
            observability=self._observability_writer,
        )
        await session_mgr.start()
        self._runtime.begin(
            todo.phase_id, session_manager=session_mgr, started_at=datetime.now(UTC)
        )

        # ADR-063: convert typed RepositoryRef → HTTPS URL at the workspace seam.
        repo_urls = [r.https_url for r in (repos or [])]
        result = await self.provision(
            todo=todo,
            phase=phase,
            aggregate=aggregate,
            session_id=session_id,
            repo_urls=repo_urls,
            completed_phase_ids=completed_phase_ids,
            phase_outputs=phase_outputs,
        )
        self._runtime.attach_workspace(
            todo.phase_id,
            workspace=result.workspace,
            workspace_cm=result.workspace_cm,
            agent_env=result.agent_env,
            claude_cmd=result.claude_cmd,
            # The phase's own declaration, handed over here because this is the
            # only frame that holds both it and the workspace it describes. The
            # terminal paths that need it are given an exception and a phase id
            # and have no definition to ask (#1231).
            delivers_repo_changes=phase.delivers_repo_changes,
        )
        await self._runtime.record_starting_point(todo.phase_id)
        # BEFORE the agent is launched and AFTER the workspace exists, which is
        # the only window in which the quarantine push can be tested with
        # nothing riding on it. Raising here fails the phase while the only
        # thing spent is provisioning (#1393).
        await self._runtime.rehearse_quarantine_path(todo.phase_id, execution_id=todo.execution_id)
        aggregate.provision_workspace_completed(result.command)
        await self._journal.append(aggregate)

    async def provision(
        self,
        *,
        todo: TodoItem,
        phase: ExecutablePhase,
        aggregate: WorkflowExecutionAggregate,
        session_id: str,
        repo_urls: list[str],
        completed_phase_ids: list[str],
        phase_outputs: PhaseOutputCache,
    ) -> ProvisionResult:
        """Provision this phase's own workspace and build its ProvisionResult."""
        provision_handler = WorkspaceProvisionHandler(
            workspace_service=self._workspace_service,
            prompt_builder=self._prompt_builder,
            command_builder=self._command_builder,
            claude_plugin_materializer=self._claude_plugin_materializer,
            skill_materializer=self._skill_materializer,
        )
        return await provision_handler.handle(
            todo=todo,
            phase=phase,
            workflow_id=aggregate.workflow_id or "",
            session_id=session_id,
            repos=repo_urls,
            artifacts=self._collector(),
            completed_phase_ids=completed_phase_ids,
            phase_outputs=phase_outputs,
            inputs=self._inputs,
        )

    async def keep_unfinished_output(
        self,
        todo: TodoItem,
        phase: ExecutablePhase,
        *,
        workspace: ManagedWorkspace,
        workflow_id: str,
    ) -> list[str]:
        """Store what a phase wrote before the run that produced it is torn down.

        Runs while the workspace is still alive, which is the only window there
        is: `_fail_execution` abandons it a few frames up. Never raises and
        never salvages from the transcript - the phase's outcome is already
        decided and is reported where failures are reported; the question here
        is only what survives it.
        """
        assert todo.phase_id is not None
        kept = await self._collector().collect_from_unfinished_phase(
            workspace=workspace,
            workflow_id=workflow_id,
            phase_id=todo.phase_id,
            execution_id=todo.execution_id,
            session_id=todo.session_id or "",
            phase_name=phase.name,
            output_artifact_types=phase.output_artifact_types,
            agent=self._runtime.agent_for(todo.phase_id, provider=phase.agent_config.provider),
            outcome=UnfinishedPhase.FAILED,
        )
        if kept:
            logger.warning(
                "Phase %s (%s) failed; kept %d artifact(s) it had already written "
                "under artifacts/output/ rather than discarding them with the "
                "workspace (#1321)",
                todo.phase_id,
                phase.name,
                len(kept),
            )
        return kept

    async def collect(
        self,
        todo: TodoItem,
        phase: ExecutablePhase,
        aggregate: WorkflowExecutionAggregate,
        all_artifact_ids: list[str],
        phase_outputs: PhaseOutputCache,
    ) -> None:
        """Dispatch COLLECT_ARTIFACTS."""
        assert todo.phase_id is not None
        workspace = self._runtime.workspace_for(todo.phase_id)
        if workspace is None:
            # Defense in depth: in-process this branch is unreachable
            # (the runtime gives up a phase's workspace only after
            # on_phase_completed locks the phase at rank 99, and
            # get_pending filters stale items), but a lock-bypassing
            # projection writer (e.g. a future out-of-process consumer on
            # a shared Postgres store) could resurrect a stale todo.
            # Skip it instead of crashing the workflow with KeyError.
            logger.warning(
                "Skipping stale COLLECT_ARTIFACTS for finalized phase %s "
                "(execution %s): no active workspace",
                todo.phase_id,
                todo.execution_id,
            )
            return
        collection_handler = ArtifactCollectionHandler(artifact_collector=self._collector())
        result = await collection_handler.handle(
            todo=todo,
            workspace=workspace,
            workflow_id=aggregate.workflow_id or "",
            session_id=todo.session_id or "",
            phase_name=phase.name,
            output_artifact_types=phase.output_artifact_types,
            # The provider is the phase's because we launched it; the model is
            # the runtime's because only the agent's own stream said it (#1284).
            agent=self._runtime.agent_for(todo.phase_id, provider=phase.agent_config.provider),
            # From the AGGREGATE, which rebuilt it from the event stream, and
            # not from anything this process was holding: a restart between
            # the agent finishing and this point is the commonest form of the
            # "something went wrong" that the salvage exists for (#1300). This
            # replaces `self._runtime.take_last_message(...)`, which read the
            # same value out of process memory and lost it to exactly that
            # restart.
            last_agent_message=aggregate.last_agent_message_for(todo.phase_id),
            # Asked only if the collector actually has to salvage. The reading
            # costs a git inspection, and it has to happen HERE rather than on
            # the failure path because a salvaged phase does not fail (#1300).
            describe_work=partial(self._runtime.describe_work, todo.phase_id),
        )
        all_artifact_ids.extend(result.artifact_ids)
        self._runtime.record_artifacts(todo.phase_id, result.artifact_ids)
        phase_outputs.record(todo.phase_id, result.first_content, result.files)
        aggregate.artifacts_collected(result.command)
        await self._journal.append(aggregate)
