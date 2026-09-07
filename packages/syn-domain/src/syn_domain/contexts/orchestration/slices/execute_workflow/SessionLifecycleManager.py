"""SessionLifecycleManager — encapsulates agent session aggregate lifecycle.

Extracted from WorkflowExecutionEngine to reduce cyclomatic complexity.
Session creation, completion (success/failure/cancelled) was duplicated
across _execute_phase and _execute_phase_in_container with identical patterns.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions import (
    AgentSessionAggregate,
    CompleteSessionCommand,
    MarkAgentLaunchedCommand,
    OperationType,
    RecordOperationCommand,
    SessionStatus,
    StartSessionCommand,
)
from syn_shared.events import SESSION_ERROR

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
        ObservabilityRecorder,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionEngine import (
        SessionRepository,
    )

logger = logging.getLogger(__name__)


def _unstated_reason(status: str) -> str:
    """What a terminal status says when the caller supplied no reason.

    A blank `error_message` is reachable today: the processor derives it with
    `str(error)`, which is "" for any exception raised with no arguments, and
    #1196 is a `session_error` observation that reached a user saying nothing
    at all. The status is the one fact this layer always has, so it is what
    gets written when the caller has nothing to add.

    The read path has its own fallback for rows stored blank BEFORE this
    change (`session_tools_verdict.NO_REASON_RECORDED`). This one is more
    specific because it still knows the status, and it cannot be shared: the
    domain must not import from the adapters.
    """
    return f"session ended with status '{status}' and no reason was recorded"


class SessionLifecycleManager:
    """Manages AgentSession aggregate lifecycle for a single phase execution.

    Handles the optional nature of session tracking — all methods are no-ops
    when the repository is None, eliminating conditional checks at call sites.
    """

    def __init__(
        self,
        repository: SessionRepository | None,
        session_id: str,
        workflow_id: str,
        execution_id: str,
        phase_id: str,
        agent_provider: str,
        agent_model: str | None,
        repos: list[str] | None = None,
        observability: ObservabilityRecorder | None = None,
    ) -> None:
        self._repo = repository
        self._observability = observability
        self._session_id = session_id
        self._session: AgentSessionAggregate | None = None
        self._workflow_id = workflow_id
        self._execution_id = execution_id
        self._phase_id = phase_id
        self._agent_provider = agent_provider
        self._agent_model = agent_model
        self._repos = list(repos) if repos else []

    @property
    def session(self) -> AgentSessionAggregate | None:
        return self._session

    async def _record_terminal_status(self, status: str, error_message: str) -> None:
        """Leave an observable trace that this session ended badly.

        A run that dies before the agent starts emits no telemetry at all, so
        it existed only in the domain lane - countable there, invisible
        everywhere else, and absent from the dashboard entirely.

        DELIBERATELY a session_error, never a session_summary. A summary is a
        USAGE record, and TimescaleSessionCostQuery selects the latest one
        (ORDER BY time DESC LIMIT 1). complete_failure also fires for a session
        whose agent RAN and then exited non-zero - the stream processor has
        already written that session's real summary by then, so appending a
        zero-token summary here would supersede it and report real work as
        free. That is the exact silently-cheap failure this change exists to
        remove, and it would have been reintroduced one layer down.

        session_error carries no token fields, so nothing can price it, while
        the session still becomes countable: the canonical session count reads
        DISTINCT session_id across ALL observation types, not just usage rows.

        Secondary failures are swallowed. This runs on the error path; losing
        the domain-lane completion because telemetry was unreachable would
        trade a visibility gap for a correctness one.
        """
        if self._observability is None:
            return
        try:
            await self._observability.record_observation(
                session_id=self._session_id,
                observation_type=SESSION_ERROR,
                data={
                    "status": status,
                    "error_message": error_message.strip() or _unstated_reason(status),
                    "model": self._agent_model,
                },
                execution_id=self._execution_id,
                phase_id=self._phase_id,
            )
        except Exception as obs_err:
            logger.warning(
                "Failed to record terminal status for session %s: %s",
                self._session_id,
                obs_err,
            )

    async def start(self) -> None:
        """Create and persist a new session aggregate. No-op if repo is None."""
        if self._repo is None:
            return

        self._session = AgentSessionAggregate()
        cmd = StartSessionCommand(
            aggregate_id=self._session_id,
            workflow_id=self._workflow_id,
            execution_id=self._execution_id,
            phase_id=self._phase_id,
            agent_provider=self._agent_provider,
            agent_model=self._agent_model,
            repos=list(self._repos),
        )
        self._session.start_session(cmd)
        await self._repo.save(self._session)
        logger.debug("Session started: %s (phase: %s)", self._session_id, self._phase_id)

    async def mark_launched(self) -> None:
        """Record that an agent process demonstrably existed for this session.

        Called by the stream once the process is known to exist, never by the
        code that merely decided to start one. This is the real discriminator
        between "the agent never ran" and "the agent ran and later failed" -
        both leave zero recorded tokens on the failure path, so
        `complete_failure` alone can't tell them apart (#1047, #1065).

        Applied to the aggregate first and persisted second, and that order is
        the entire guarantee. A save that fails leaves the event uncommitted,
        so the next save re-appends it; and the completion event this same
        in-memory aggregate emits carries the fact whether or not this write
        ever landed. Losing it therefore costs promptness - the dashboard
        learns of the launch later - and never the answer itself, which is
        what makes swallowing the failure defensible rather than lossy.

        It also has to be swallowed: this runs inside the live agent's output
        loop, and a bookkeeping write is not worth killing a running agent
        for.
        """
        if self._session is None or self._repo is None:
            return

        self._session.mark_agent_launched(MarkAgentLaunchedCommand(aggregate_id=self._session_id))
        try:
            await self._repo.save(self._session)
        except Exception as launch_err:
            logger.warning(
                "Failed to persist agent launch for session %s "
                "(the fact is held on the aggregate and rides the next save): %s",
                self._session_id,
                launch_err,
            )

    async def complete_success(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_creation_tokens: int,
        cache_read_tokens: int,
        total_tokens: int,
        duration_seconds: float,
        source: str,
    ) -> None:
        """Record token usage and complete session as successful."""
        if self._session is None or self._repo is None:
            return

        if total_tokens > 0:
            record_cmd = RecordOperationCommand(
                aggregate_id=self._session_id,
                operation_type=OperationType.MESSAGE_RESPONSE,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_creation_tokens=cache_creation_tokens,
                cache_read_tokens=cache_read_tokens,
                total_tokens=total_tokens,
                success=True,
                duration_seconds=duration_seconds,
                metadata={"phase_id": self._phase_id, "source": source},
            )
            self._session.record_operation(record_cmd)

        complete_cmd = CompleteSessionCommand(
            aggregate_id=self._session_id,
            success=True,
        )
        self._session.complete_session(complete_cmd)
        await self._repo.save(self._session)
        logger.debug("Session completed: %s (success, tokens: %d)", self._session_id, total_tokens)

    async def complete_failure(self, *, error_message: str) -> None:
        """Complete session as failed. Swallows secondary errors."""
        if self._session is None or self._repo is None:
            return

        try:
            complete_cmd = CompleteSessionCommand(
                aggregate_id=self._session_id,
                success=False,
                error_message=error_message,
            )
            self._session.complete_session(complete_cmd)
            await self._repo.save(self._session)
            await self._record_terminal_status("failed", error_message)
            logger.debug("Session completed: %s (failed: %s)", self._session_id, error_message)
        except Exception as session_err:
            logger.warning("Failed to complete session %s: %s", self._session_id, session_err)

    async def complete_cancelled(self, *, reason: str) -> None:
        """Complete session as cancelled. Swallows secondary errors."""
        if self._session is None or self._repo is None:
            return

        try:
            complete_cmd = CompleteSessionCommand(
                aggregate_id=self._session_id,
                success=False,
                final_status=SessionStatus.CANCELLED,
                error_message=reason,
            )
            self._session.complete_session(complete_cmd)
            await self._repo.save(self._session)
            await self._record_terminal_status("cancelled", reason)
            logger.debug("Session completed (cancelled): %s", self._session_id)
        except Exception as sess_err:
            logger.warning(
                "Failed to complete session %s during cancel: %s", self._session_id, sess_err
            )
