"""SessionLifecycleManager — encapsulates agent session aggregate lifecycle.

Extracted from WorkflowExecutionEngine to reduce cyclomatic complexity.
Session creation, completion (success/failure/cancelled) was duplicated
across _execute_phase and _execute_phase_in_container with identical patterns.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import uuid4

from syn_domain.contexts.agent_sessions import (
    AgentSessionAggregate,
    CompleteSessionCommand,
    CompleteSessionHandler,
    InvocationStatus,
    MarkAgentLaunchedCommand,
    OperationType,
    RecordOperationCommand,
    RecordOperationHandler,
    RecordSessionInvocationCommand,
    SessionInvocationState,
    SessionStatus,
    StartSessionCommand,
    save_reapplying,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.announced_model import (
    announced_model_from,
)
from syn_shared.events import SESSION_ERROR
from syn_shared.observed_model import OBSERVED_MODEL_KEY, REQUESTED_MODEL_KEY

if TYPE_CHECKING:
    from collections.abc import Callable

    from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
        ObservabilityRecorder,
    )

    # WorkflowExecutionEngine no longer exists; the protocol lives here. The
    # dangling import made `SessionRepository` Unknown, so pyright checked
    # nothing this manager did with its repository (#1034).
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
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
        #: The REQUESTED model (often an alias). Never written as ``model`` on
        #: an observation (ADR-067).
        self._agent_model = agent_model
        #: The model the harness reported, once the stream has said.
        self._observed_model: str | None = None
        self._repos = list(repos) if repos else []
        self._invocation: SessionInvocationState | None = None
        #: Commands applied to ``_session`` since it was last persisted, kept
        #: so a save rejected by a concurrent writer can re-decide them
        #: against the current stream instead of dropping them (#1398).
        self._pending: list[Callable[[AgentSessionAggregate], None]] = []

    def _issue(self, command: Callable[[AgentSessionAggregate], None]) -> None:
        assert self._session is not None
        command(self._session)
        self._pending.append(command)

    async def _save(self) -> None:
        """Persist pending commands, reapplying them over any concurrent write."""
        assert self._session is not None and self._repo is not None
        self._session = await save_reapplying(
            self._repo, self._session_id, self._session, tuple(self._pending)
        )
        self._pending.clear()
        if self._invocation is not None:
            # A reapplied bind keeps whichever binding the stream already had.
            current = {i.invocation_id: i for i in self._session.invocations}
            self._invocation = current.get(self._invocation.invocation_id, self._invocation)

    def note_observed_model(self, model: str | None) -> None:
        """Record the model the harness reported. First non-blank report wins."""
        if self._observed_model is None:
            self._observed_model = announced_model_from(model)

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
                    # What ran, if the harness ever said - usually it had not
                    # by the time a session dies - and what was asked for,
                    # always as its own key (ADR-067).
                    OBSERVED_MODEL_KEY: self._observed_model,
                    REQUESTED_MODEL_KEY: self._agent_model,
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
            capture_profile="local-spool/1",
            phase_id=self._phase_id,
            agent_provider=self._agent_provider,
            agent_model=self._agent_model,
            repos=list(self._repos),
        )
        self._session.start_session(cmd)
        await self._repo.save(self._session)
        logger.debug("Session started: %s (phase: %s)", self._session_id, self._phase_id)

    async def prepare_invocation(self, harness: str) -> SessionInvocationState | None:
        """Persist intent before every launch, including capacity retries."""
        if self._repo is None:
            return
        if self._session is None:
            raise ValueError("session must be started before registering an invocation")
        invocation = SessionInvocationState(
            invocation_id=str(uuid4()),
            attempt_id=str(uuid4()),
            harness=harness,
        )
        command = RecordSessionInvocationCommand(
            aggregate_id=self._session_id, invocation=invocation
        )
        self._issue(lambda session: session.record_invocation(command))
        # Failure propagates to admission: no controlled process may launch yet.
        await self._save()
        self._invocation = invocation
        return invocation

    def _advance_invocation(self, invocation: SessionInvocationState) -> None:
        command = RecordSessionInvocationCommand(
            aggregate_id=self._session_id, invocation=invocation
        )
        self._issue(lambda session: session.record_invocation(command))
        self._invocation = invocation

    async def finish_invocation(
        self,
        *,
        native_session_id: str | None,
        status: InvocationStatus,
    ) -> None:
        if self._invocation is None or self._session is None or self._repo is None:
            return
        self._advance_invocation(
            SessionInvocationState(
                invocation_id=self._invocation.invocation_id,
                attempt_id=self._invocation.attempt_id,
                harness=self._invocation.harness,
                native_session_id=native_session_id or self._invocation.native_session_id,
                status=status,
            )
        )
        try:
            await self._save()
        except Exception:
            # Keep the uncommitted fact for the normal session completion save.
            # Post-launch recording failure must not change the work's result.
            logger.exception("Invocation result remains pending for session %s", self._session_id)

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

        launched = MarkAgentLaunchedCommand(aggregate_id=self._session_id)
        self._issue(lambda session: session.mark_agent_launched(launched))
        if self._invocation is not None:
            self._advance_invocation(
                self._invocation.model_copy(
                    update={"status": InvocationStatus.LAUNCHED},
                )
            )
        try:
            await self._save()
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
        """Record token usage and complete session as successful.

        Both writes go through their slice handlers rather than this
        manager's own aggregate. Two entry points for one command is what let
        ``RecordOperationHandler`` sit unimplemented and unnoticed (#1034);
        the handler is now the only way a session records an operation.

        The recorder this manager already holds is handed to it, because an
        operation has to land on the observation lane to be readable at
        ``GET /sessions/{id}``. A manager built without one records the
        session's tokens and no timeline row, and the handler says so.

        The roll-up is recorded as SESSION_COMPLETED, not MESSAGE_RESPONSE.
        It is not an LLM reply - it is this phase's terminal fact, with the
        run's totals on it - and under the old name it was also unreadable:
        MESSAGE_RESPONSE is mapped to no observation type, deliberately and
        correctly, so every production call reached the handler and wrote
        nothing to the lane the read path serves ``operations`` from. That is
        the counterpart of the ``session_error`` row ``_record_terminal_status``
        writes when a phase ends badly; only the failure half existed (#1034).

        The handlers load their own copy of the session, so they must run
        against a stored aggregate that is up to date, and they must run in
        sequence - a second write against the pre-record version would be a
        concurrency conflict.
        """
        if self._session is None or self._repo is None:
            return

        # Flush first: mark_launched swallows its save failure by design, so
        # this manager's aggregate may still be holding an AgentLaunched the
        # store has never seen. The handlers would load without it and the
        # fact would be lost for good (#1047, #1065). A save with nothing
        # uncommitted does no I/O, so this costs nothing in the normal case.
        await self._save()

        if total_tokens > 0:
            record_cmd = RecordOperationCommand(
                aggregate_id=self._session_id,
                operation_type=OperationType.SESSION_COMPLETED,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_creation_tokens=cache_creation_tokens,
                cache_read_tokens=cache_read_tokens,
                total_tokens=total_tokens,
                success=True,
                duration_seconds=duration_seconds,
                metadata={"phase_id": self._phase_id, "source": source},
            )
            recorded = await RecordOperationHandler(
                repository=self._repo, observations=self._observability
            ).handle(record_cmd)
            if recorded.diverged:
                # The handler already logged the failure with its traceback.
                # This adds what it has no way to know - which execution and
                # phase lost the row - so the gap can be tied to a run instead
                # of being inferred later from a timeline that is short by one.
                logger.error(
                    "Session %s completed but its timeline row was lost "
                    "(execution %s, phase %s): %s. Lane 1 has the operation and "
                    "its tokens; GET /sessions/%s will be missing the completion.",
                    self._session_id,
                    self._execution_id,
                    self._phase_id,
                    recorded.reason,
                    self._session_id,
                )

        complete_cmd = CompleteSessionCommand(
            aggregate_id=self._session_id,
            success=True,
        )
        await CompleteSessionHandler(repository=self._repo).handle(complete_cmd)

        # The handlers advanced the stream; the copy held here is now behind
        # it. Re-read so `session` never hands a caller a stale aggregate.
        self._session = await self._repo.get_by_id(self._session_id)
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
            self._issue(lambda session: session.complete_session(complete_cmd))
            await self._save()
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
            self._issue(lambda session: session.complete_session(complete_cmd))
            await self._save()
            await self._record_terminal_status("cancelled", reason)
            logger.debug("Session completed (cancelled): %s", self._session_id)
        except Exception as sess_err:
            logger.warning(
                "Failed to complete session %s during cancel: %s", self._session_id, sess_err
            )
