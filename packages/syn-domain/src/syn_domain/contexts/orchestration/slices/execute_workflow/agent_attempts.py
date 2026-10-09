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

WHAT IS RETRIED IS A LAUNCH THAT NEVER STARTED, and only that. A retry re-runs
the original prompt against the SAME workspace, so it is idempotent exactly
while the attempt it replaces did nothing: an agent that had already edited a
file, run a command or pushed a branch would do it a second time from a tree
that is no longer the one the prompt was written against. So an attempt that
got anywhere fails the way it failed before this module existed, however busy
the upstream was when it stopped. See `_phase_got_somewhere`.

AND ONE DIFFERENT AGENT, ONCE (PC-83). A phase that declared a
`fallback_agent` is re-run on it when its own provider could not serve it at
all - capacity that outlived the retries above, a spent quota, or a content
filter that refused the request, neither of which is ever retried - and only
under the same rule: the failed attempt got nowhere.
The result names the agent that produced it, on the completion command, so the
execution records the model that actually ran rather than the one declared.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions import InvocationStatus
from syn_domain.contexts.orchestration.slices.execute_workflow.agent_launch_observation import (
    observer_for,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
    ObservabilityCollector,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_cost_limit import (
    PhaseCostLimit,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.upstream_failure import (
    UPSTREAM_FAILURES,
)
from syn_shared.agents import runner_for_provider
from syn_shared.env_constants import ENV_SYN_PHASE_DEADLINE, ENV_SYN_PHASE_TIMEOUT_SECONDS

from .invocation_attempt import invocation_environment, registered_attempt

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoItem
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        AgentConfiguration,
        ExecutablePhase,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.busy_upstream import (
        AttemptGrant,
        PhaseAttempts,
        UpstreamRetryPolicy,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
        ObservabilityRecorder,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
        AgentExecutionResult,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.phase_push import (
        PushObserver,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.phase_runtime import (
        PhaseLaunch,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
        AgentHandlerProtocol,
        Runner,
    )

logger = logging.getLogger(__name__)


def _phase_deadline_environment(attempts: PhaseAttempts) -> dict[str, str]:
    """What the agent is told about its clock: when it ends, and out of how much."""
    return {
        ENV_SYN_PHASE_DEADLINE: attempts.deadline.isoformat(timespec="seconds"),
        ENV_SYN_PHASE_TIMEOUT_SECONDS: str(int(attempts.timeout_seconds)),
    }


def _attempt_is_settled(result: AgentExecutionResult) -> bool:
    """Whether this attempt is the phase's answer, whatever the retry policy thinks.

    A run that exited zero has nothing left to try. An interrupted one is
    checked HERE, ahead of the policy, because a cancelled phase also exits
    non-zero and can carry a capacity reason: leave it to the retry decision
    and the phase restarts work an operator just stopped.
    """
    return result.stream_result.interrupt_requested or (
        result.command is not None and result.command.exit_code == 0
    )


def _phase_got_somewhere(result: AgentExecutionResult, collector: ObservabilityCollector) -> bool:
    """Whether this phase's agent has done anything a rerun would have to redo.

    ASKED IN THE DIRECTION THAT FAILS SAFE. The question a retry actually needs
    answered is the negative one - "did this attempt do NOTHING" - and the
    honest way to answer it is to look for any sign of life and report its
    absence, never to look for the particular signs a parser happens to
    recognise and read their absence as silence. Those are the same answer only
    while the parser knows every shape the harness emits, which it does not and
    cannot: a `thinking` block, a hook-delivered tool call, a codex item type
    shipped next month. Each is an attempt that got somewhere; each was silence
    to the narrower predicate this replaced; and each bought a rerun of the
    whole prompt over the workspace it had already changed.

    So the two witnesses are both evidence the attempt recorded ANYWAY, and
    both are deliberately unselective:

    - ``collector.saw_agent_activity`` - set by any assistant turn with any
      content, any hook event, any subagent lifecycle event, and any codex
      ``item.started`` / ``item.completed`` of any type. See that property for
      why each counts. It is the primary witness and the one that scales: a new
      event shape is covered by the branch that already forwards it here, not
      by remembering to teach this function about it.
    - ``last_agent_message is not None`` - an ASSISTANT TURN, kept because it
      catches the one path that reaches the caller without touching the
      collector at all: a claude terminal ``result`` line carrying the agent's
      words. ``None`` on this field already means "the agent said nothing on
      this stream", a fact the artifact path depends on (#1195), so it is read
      here rather than re-derived.

    Neither is a flag set by the retry path for the retry path, which would be
    a claim about work rather than a trace of it.

    Deliberately NOT token counts: a request that reached the model and was
    refused for capacity can carry input tokens, and that is a bill, not work
    to preserve. Treating it as work would stop the retry this module exists
    for from ever happening.
    """
    return collector.saw_agent_activity or result.stream_result.last_agent_message is not None


def _invocation_outcome(result: AgentExecutionResult) -> InvocationStatus:
    if result.launch_failed:
        return InvocationStatus.LAUNCH_FAILED
    if result.stream_result.interrupt_requested:
        return InvocationStatus.CANCELLED
    return InvocationStatus.COMPLETED if result.exit_code == 0 else InvocationStatus.FAILED


async def run_phase_agent(
    *,
    handler: AgentHandlerProtocol,
    todo: TodoItem,
    phase: ExecutablePhase,
    launch: PhaseLaunch,
    session_id: str,
    observability: ObservabilityRecorder | None,
    retry_policy: UpstreamRetryPolicy,
    on_push: PushObserver | None = None,
) -> AgentExecutionResult:
    """Run this phase's agent and return the result it ends on.

    The result is final in the only sense the caller needs: there is no further
    attempt to come, and `stream_result.error_reason` / `command.exit_code` on
    it are the phase's own outcome, reported exactly as the agent gave them.
    Which provider parses the stream, how the run is observed, how long it may
    take, how many times it was tried and on which agent are all settled in
    here. `command.agent_provider` / `agent_model` say which agent it was, and
    `primary_failure` is set when it was the fallback and the primary's own
    failure is part of the story.
    """
    assert todo.phase_id is not None
    # ONE deadline for the phase, fixed here, before anything runs. Every
    # attempt and every backoff is drawn from it - the fallback's included -
    # so what a phase is configured to cost in time is what it can cost: a
    # per-attempt timeout made three attempts at a 3600-second phase into
    # three hours and three phases' money.
    attempts = retry_policy.begin(timeout_seconds=phase.effective_timeout_seconds)
    # ONE cost limit for the phase, for the same reason as the deadline above:
    # every attempt spends from it, so neither a retry nor the fallback can
    # reset what was spent (#1376). None when the phase declared no
    # `max_cost_usd`.
    cost_limit = PhaseCostLimit(phase.max_cost_usd) if phase.max_cost_usd is not None else None
    run = _AgentRun(
        handler=handler,
        todo=todo,
        launch=launch,
        session_id=session_id,
        observability=observability,
        attempts=attempts,
        cost_limit=cost_limit,
        on_push=on_push,
    )
    primary = await run.until_final(
        phase.agent_config,
        claude_cmd=launch.claude_cmd,
        agent_env=launch.agent_env,
        grant=attempts.first_attempt(),
    )
    fallback = launch.fallback
    if fallback is None or _attempt_is_settled(primary.result):
        return primary.result
    grant = attempts.fallback_attempt(
        reason=primary.result.stream_result.error_reason, work_done=primary.got_somewhere
    )
    if grant is None:
        return primary.result
    logger.warning(
        "Phase %s: %s/%s could not serve it (%s) - running it once on fallback %s/%s",
        todo.phase_id,
        phase.agent_config.provider,
        phase.agent_config.model,
        primary.result.stream_result.error_reason,
        fallback.agent.provider,
        fallback.agent.model,
    )
    second = await run.once(
        fallback.agent,
        claude_cmd=fallback.claude_cmd,
        agent_env=fallback.agent_env,
        grant=grant,
    )
    if not _attempt_is_settled(second.result) or second.result.exit_code != 0:
        second.result.primary_failure = _why_the_primary_failed(phase.agent_config, primary.result)
    return second.result


def _why_the_primary_failed(agent: AgentConfiguration, result: AgentExecutionResult) -> str:
    """The primary's failure, as the fallback's error restates it."""
    reason = result.stream_result.error_reason
    quota = UPSTREAM_FAILURES.quota_of(reason)
    said = f"{quota.account()}: {reason}" if quota is not None else reason
    return f"Primary agent {agent.provider}/{agent.model} failed: {said}"


class _Ended:
    """How one agent's run ended: its final result, and whether it got anywhere."""

    __slots__ = ("got_somewhere", "result")

    def __init__(self, result: AgentExecutionResult, *, got_somewhere: bool) -> None:
        self.result = result
        self.got_somewhere = got_somewhere


class _AgentRun:
    """What every attempt of one phase shares, whichever agent it runs on."""

    def __init__(
        self,
        *,
        handler: AgentHandlerProtocol,
        todo: TodoItem,
        launch: PhaseLaunch,
        session_id: str,
        observability: ObservabilityRecorder | None,
        attempts: PhaseAttempts,
        cost_limit: PhaseCostLimit | None,
        on_push: PushObserver | None = None,
    ) -> None:
        self._handler = handler
        self._todo = todo
        self._launch = launch
        self._session_id = session_id
        self._observability = observability
        self._attempts = attempts
        self._cost_limit = cost_limit
        self._on_push = on_push

    async def until_final(
        self,
        agent: AgentConfiguration,
        *,
        claude_cmd: list[str],
        agent_env: dict[str, str],
        grant: AttemptGrant,
    ) -> _Ended:
        """Run ``agent`` for as many attempts as a busy upstream earns it."""
        runner, collector = self._for(agent)
        while True:
            result = await self._dispatch(agent, runner, collector, claude_cmd, agent_env, grant)
            got_somewhere = _phase_got_somewhere(result, collector)
            if _attempt_is_settled(result):
                return _Ended(result, got_somewhere=got_somewhere)
            successor = await self._attempts.wait_before_retry(
                reason=result.stream_result.error_reason, work_done=got_somewhere
            )
            if successor is None:
                # Final, and `result` is the failed one: the reason it carries is
                # reported by the caller exactly as the agent gave it, whether the
                # budget ran out, the deadline did, the attempt had already got
                # somewhere, or the failure never qualified for a retry.
                return _Ended(result, got_somewhere=got_somewhere)
            grant = successor
            logger.warning(
                "Upstream was busy (phase=%s): %s - attempt %d of %d",
                self._todo.phase_id,
                result.stream_result.error_reason,
                self._attempts.attempt,
                self._attempts.max_attempts,
            )

    async def once(
        self,
        agent: AgentConfiguration,
        *,
        claude_cmd: list[str],
        agent_env: dict[str, str],
        grant: AttemptGrant,
    ) -> _Ended:
        """Run ``agent`` exactly once: the fallback is not itself retried."""
        runner, collector = self._for(agent)
        result = await self._dispatch(agent, runner, collector, claude_cmd, agent_env, grant)
        return _Ended(result, got_somewhere=_phase_got_somewhere(result, collector))

    def _for(self, agent: AgentConfiguration) -> tuple[Runner, ObservabilityCollector]:
        """The parser and the Lane-2 collector for ``agent``, shared by all its attempts."""
        assert self._todo.phase_id is not None
        # Raises on an unknown or removed provider instead of defaulting to the
        # claude parser. The execution boundary (_build_agent_config_from_phase)
        # already rejected it, so reaching that raise means a new entry point
        # skipped the gate.
        runner: Runner = runner_for_provider(agent.provider, phase_id=self._todo.phase_id)
        # One collector PER AGENT, built once and shared across that agent's
        # attempts, so the cost ledger keeps every attempt's records and each
        # is priced against the model that actually made it.
        collector = ObservabilityCollector(
            writer=self._observability,
            session_id=self._session_id,
            execution_id=self._todo.execution_id,
            phase_id=self._todo.phase_id,
            workspace_id=getattr(self._launch.workspace, "workspace_id", None),
            requested_model=agent.model,
        )
        return runner, collector

    async def _dispatch(
        self,
        agent: AgentConfiguration,
        runner: Runner,
        collector: ObservabilityCollector,
        claude_cmd: list[str],
        agent_env: dict[str, str],
        grant: AttemptGrant,
    ) -> AgentExecutionResult:
        # NO ATTEMPT IS DISPATCHED ON A TIMEOUT THIS FRAME COMPUTED. Every one
        # runs on the number inside an `AttemptGrant`, which `busy_upstream`
        # produced from the same reading of the clock that approved the
        # attempt: a timeout of 0 is read by the workspace provider as NO
        # timeout, and computing it here once let an expired deadline do that.
        # The agent is told that deadline, read off the same object that
        # enforces it, because it cannot see a clock and phases died at 124
        # holding finished, unpushed work (#1546).
        env = {**agent_env, **_phase_deadline_environment(self._attempts)}
        session_manager = self._launch.session_manager
        async with registered_attempt(session_manager, runner) as invocation:
            result = await self._handler.handle(
                todo=self._todo,
                workspace=self._launch.workspace,
                agent_env=invocation_environment(env, invocation),
                claude_cmd=claude_cmd,
                session_id=self._session_id,
                agent_model=agent.model,
                timeout_seconds=grant.timeout_seconds,
                collector=collector,
                runner=runner,
                on_launch=observer_for(session_manager),
                cost_limit=self._cost_limit,
                on_push=self._on_push,
            )
        if session_manager is not None:
            await session_manager.finish_invocation(
                native_session_id=result.stream_result.leader_native_session_id,
                status=_invocation_outcome(result),
            )
        if result.command is not None:
            result.command.produced_by(provider=agent.provider, model=agent.model)
        return result
