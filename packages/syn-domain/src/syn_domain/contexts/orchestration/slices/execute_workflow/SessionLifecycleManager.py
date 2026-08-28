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
    OperationType,
    RecordOperationCommand,
    SessionStatus,
    StartSessionCommand,
)
from syn_shared.events import SESSION_SUMMARY

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
        ObservabilityRecorder,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionEngine import (
        SessionRepository,
    )

logger = logging.getLogger(__name__)


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

    async def _record_terminal_summary(self, status: str, error_message: str) -> None:
        """Leave an observable trace for a session that produced no telemetry.

        A run that dies before the agent starts emits no token_usage and no
        summary of its own, so it existed only in the domain lane - countable
        there, invisible everywhere else, and absent from the dashboard
        entirely. Recording a zero-token summary makes the failure a FACT that
        every read path already knows how to consume, rather than something
        each consumer has to learn to infer from an absence.

        Zero tokens here is a measurement, not a placeholder: the agent
        genuinely never ran. `status` distinguishes it from a session that did
        work, so nothing prices it as free work.

        Secondary failures are swallowed. This runs on the error path; losing
        the domain-lane completion because telemetry was unreachable would
        trade a visibility gap for a correctness one.
        """
        if self._observability is None:
            return
        try:
            await self._observability.record_observation(
                session_id=self._session_id,
                observation_type=SESSION_SUMMARY,
                data={
                    "total_input_tokens": 0,
                    "total_output_tokens": 0,
                    "cache_creation_tokens": 0,
                    "cache_read_tokens": 0,
                    "total_tokens": 0,
                    "total_cost_usd": 0,
                    "status": status,
                    "error_message": error_message,
                    "model": self._agent_model,
                },
                execution_id=self._execution_id,
                phase_id=self._phase_id,
            )
        except Exception as obs_err:
            logger.warning(
                "Failed to record terminal summary for session %s: %s",
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
            await self._record_terminal_summary("failed", error_message)
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
            await self._record_terminal_summary("cancelled", reason)
            logger.debug("Session completed (cancelled): %s", self._session_id)
        except Exception as sess_err:
            logger.warning(
                "Failed to complete session %s during cancel: %s", self._session_id, sess_err
            )
