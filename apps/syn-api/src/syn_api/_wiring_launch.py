"""Launch wiring: the handlers that start an execution, and archive's barrier.

Split out of ``_wiring`` (#1588). Every way an execution starts records the
launch on its template's stream, so both start handlers are built here, side by
side, where a third one added later is easy to see beside them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration._shared.template_launch import TemplateLaunches

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration import StartResumeHandler
    from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
        ExecuteWorkflowHandler,
    )


async def get_execute_workflow_handler() -> ExecuteWorkflowHandler:
    """Single composition root for ExecuteWorkflowHandler.

    Both the synchronous POST /workflows/{id}/execute route and the
    background dispatcher path go through this. Keeping the construction
    in one place prevents drift like #726's missed phase_plugin_resolver
    wiring, where one path materialized claude plugins into workspaces and
    the other silently skipped them.

    WHY (issue #726): bind the resolution service's per-phase resolver so
    ``ExecuteWorkflowHandler`` populates ``ExecutablePhase.claude_plugins``
    with lock-resolved entries before dispatch reaches the processor.

    WHY (issue #772): mirrors the claude plugin wiring for skills -- binds
    ``SkillResolutionService.resolve_for_phase`` so
    ``ExecutablePhase.skills`` is populated the same way.
    """
    from syn_adapters.github.client import get_github_client
    from syn_adapters.github.source_commit_resolver import GitHubSourceCommitResolver
    from syn_api._wiring import (
        get_claude_plugin_resolution_service,
        get_execution_processor,
        get_skill_resolution_service,
        get_workflow_repository,
    )
    from syn_api._wiring_admission import get_maintenance_port
    from syn_domain.contexts.orchestration import ExecuteWorkflowHandler

    processor = await get_execution_processor()
    resolution_service = await get_claude_plugin_resolution_service()
    skill_resolution_service = await get_skill_resolution_service()

    return ExecuteWorkflowHandler(
        processor=processor,
        workflow_repository=get_workflow_repository(),
        # #1588: every launch is recorded on the template's stream before the
        # execution starts, which is what lets archive refuse one race-free.
        launches=TemplateLaunches(get_workflow_repository()),
        phase_plugin_resolver=resolution_service.resolve_for_phase,
        phase_skill_resolver=skill_resolution_service.resolve_for_phase,
        # #1387: the backstop. Both admission paths refuse earlier and more
        # informatively than this, but a path added later that only knows about
        # the handler is still refused rather than silently admitted.
        maintenance=get_maintenance_port(),
        # #1457: every start records the commit each repository was at, so a
        # resume of it can name the code its parent ran against.
        commit_resolver=GitHubSourceCommitResolver(get_github_client),
    )


async def _build_resume_handler() -> StartResumeHandler:
    """The resume start handler, built when a resume is first requested."""
    from syn_adapters.github.client import get_github_client
    from syn_adapters.github.remote_branch_reader import GitHubRemoteBranchReader
    from syn_api._wiring import (
        get_execution_processor,
        get_workflow_execution_repository,
        get_workflow_repository,
    )
    from syn_api._wiring_admission import get_maintenance_port
    from syn_domain.contexts.orchestration import StartResumeHandler

    return StartResumeHandler(
        await get_execution_processor(),
        get_workflow_execution_repository(),
        maintenance=get_maintenance_port(),
        # #1513: confirms the branch the parent pushed is still where it was
        # left, and finds the PR open from it, before the child continues it.
        remote_branches=GitHubRemoteBranchReader(get_github_client),
        # #1588: a resumed child is a launch of its template like any other.
        launches=TemplateLaunches(get_workflow_repository()),
    )


class ExecutionProjectionBarrier:
    """``ProjectionBarrier`` over the running subscription's checkpoints (#1588).

    Fails closed: with no subscription there is no proof the execution
    projection is complete, so archive is refused rather than decided blind.
    The one exception is test/offline, whose in-memory projections are synced
    in-process on every publish (``sync_published_events_to_projections``) and
    so cannot lag.
    """

    async def projected_through_head(self) -> bool:
        from syn_api.services.lifecycle import _state
        from syn_domain.contexts.orchestration.slices.list_executions.projection import (
            WorkflowExecutionListProjection,
        )
        from syn_shared.settings import get_settings

        service = _state.subscription_service
        if service is None:
            return get_settings().uses_in_memory_stores
        name = WorkflowExecutionListProjection.PROJECTION_NAME
        return await service.projected_through_head(name)
