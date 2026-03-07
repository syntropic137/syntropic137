"""SessionLifecycleManager — encapsulates agent session aggregate lifecycle.

Extracted from WorkflowExecutionEngine to reduce cyclomatic complexity.
Session creation, completion (success/failure/cancelled) was duplicated
across _execute_phase and _execute_phase_in_container with identical patterns.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions._shared.value_objects import (
    OperationType,
    SessionStatus,
)
from syn_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
    AgentSessionAggregate,
)
from syn_domain.contexts.agent_sessions.domain.commands.CompleteSessionCommand import (
    CompleteSessionCommand,
)
from syn_domain.contexts.agent_sessions.domain.commands.RecordOperationCommand import (
    RecordOperationCommand,
)
from syn_domain.contexts.agent_sessions.domain.commands.StartSessionCommand import (
    StartSessionCommand,
)

if TYPE_CHECKING:
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
        agent_model: str,
    ) -> None:
        self._repo = repository
        self._session_id = session_id
        self._session: AgentSessionAggregate | None = None
        self._workflow_id = workflow_id
        self._execution_id = execution_id
        self._phase_id = phase_id
        self._agent_provider = agent_provider
        self._agent_model = agent_model

    @property
    def session(self) -> AgentSessionAggregate | None:
        return self._session

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
        )
        self._session._handle_command(cmd)
        await self._repo.save(self._session)
        logger.debug("Session started: %s (phase: %s)", self._session_id, self._phase_id)

    async def complete_success(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
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
                total_tokens=total_tokens,
                success=True,
                duration_seconds=duration_seconds,
                metadata={"phase_id": self._phase_id, "source": source},
            )
            self._session._handle_command(record_cmd)

        complete_cmd = CompleteSessionCommand(
            aggregate_id=self._session_id,
            success=True,
        )
        self._session._handle_command(complete_cmd)
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
            self._session._handle_command(complete_cmd)
            await self._repo.save(self._session)
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
            self._session._handle_command(complete_cmd)
            await self._repo.save(self._session)
            logger.debug("Session completed (cancelled): %s", self._session_id)
        except Exception as sess_err:
            logger.warning(
                "Failed to complete session %s during cancel: %s", self._session_id, sess_err
            )
