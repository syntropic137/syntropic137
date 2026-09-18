"""Running a phase's agent, for as long as a busy upstream makes that worth doing (#1303).

A phase that ends because the model provider was BUSY has not told us anything
about the change, the workspace or the platform - the request was well-formed
and the upstream simply had no capacity for it this second. Ending the
execution there discards every phase already completed and paid for. That cost
$18.63 twice in one window, both times at `verify`, the third of four phases.

So the agent is dispatched HERE rather than from the processor, and dispatched
as many times as `busy_upstream` says it is worth dispatching. This is the only
frame where nothing has been decided yet: the workspace is alive, the aggregate
has been told nothing, and the attempt that failed produced no deliverable to
protect. What a failed attempt DID spend is not lost either - the observability
collector is built once and shared across attempts, so the Lane-2 records the
cost ledger reads already account for it.

The caller gets one result and cannot tell how many attempts stand behind it,
which is the point: "the agent failed" and "the agent failed three times over
fifteen seconds" are the same fact to everything downstream, and the reason
reported is the one the agent gave, never a story about retrying.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.slices.execute_workflow.agent_launch_observation import (
    observer_for,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
    ObservabilityCollector,
)
from syn_shared.agents import runner_for_provider

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoItem
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ExecutablePhase,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.busy_upstream import (
        UpstreamRetryPolicy,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
        ObservabilityRecorder,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
        AgentExecutionResult,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.phase_runtime import (
        PhaseLaunch,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
        AgentHandlerProtocol,
        Runner,
    )

logger = logging.getLogger(__name__)


def _attempt_is_settled(result: AgentExecutionResult) -> bool:
    """Whether this attempt is the phase's answer, whatever the retry policy thinks.

    A run that exited zero has nothing left to try. An interrupted one is
    checked HERE, ahead of the policy, because a cancelled phase also exits
    non-zero and can carry a capacity reason: leave it to the signature list
    and the phase restarts work an operator just stopped.
    """
    return result.command.exit_code == 0 or result.stream_result.interrupt_requested


async def run_phase_agent(
    *,
    handler: AgentHandlerProtocol,
    todo: TodoItem,
    phase: ExecutablePhase,
    launch: PhaseLaunch,
    session_id: str,
    observability: ObservabilityRecorder | None,
    retry_policy: UpstreamRetryPolicy,
) -> AgentExecutionResult:
    """Run this phase's agent and return the result it ends on.

    The result is final in the only sense the caller needs: there is no further
    attempt to come, and `stream_result.error_reason` / `command.exit_code` on
    it are the phase's own outcome, reported exactly as the agent gave them.
    Which provider parses the stream, how the run is observed, how long it may
    take and how many times it was tried are all settled in here.
    """
    assert todo.phase_id is not None
    # Raises on an unknown or removed provider instead of defaulting to the
    # claude parser. The execution boundary (_build_agent_config_from_phase)
    # already rejected it, so reaching that raise means a new entry point
    # skipped the gate.
    runner: Runner = runner_for_provider(phase.agent_config.provider, phase_id=phase.phase_id)
    collector = ObservabilityCollector(
        writer=observability,
        session_id=session_id,
        execution_id=todo.execution_id,
        phase_id=todo.phase_id,
        workspace_id=getattr(launch.workspace, "workspace_id", None),
        agent_model=phase.agent_config.model,
    )

    attempt = 1
    while True:
        result = await handler.handle(
            todo=todo,
            workspace=launch.workspace,
            agent_env=launch.agent_env,
            claude_cmd=launch.claude_cmd,
            session_id=session_id,
            agent_model=phase.agent_config.model,
            timeout_seconds=phase.timeout_seconds or phase.agent_config.timeout_seconds,
            collector=collector,
            runner=runner,
            on_launch=observer_for(launch.session_manager),
        )
        if _attempt_is_settled(result):
            return result
        if not await retry_policy.wait_before_retry(
            reason=result.stream_result.error_reason, attempt=attempt
        ):
            # Final, and `result` is the failed one: the reason it carries is
            # reported by the caller exactly as the agent gave it, whether the
            # budget ran out or the failure never qualified for a retry.
            return result
        attempt += 1
        logger.warning(
            "Upstream was busy (phase=%s): %s - attempt %d of %d",
            todo.phase_id,
            result.stream_result.error_reason,
            attempt,
            retry_policy.max_attempts,
        )
