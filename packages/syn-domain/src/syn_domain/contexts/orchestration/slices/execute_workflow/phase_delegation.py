"""Whether a phase that declared delegation actually delegated (#894).

THE FAILURE THIS EXISTS TO STOP. A phase with ``allow_delegation: true`` whose
delegate never ran, or ran and failed, completed green: the agent did the work
itself, exited 0, wrote ``TASK_RESULT success=true``, and the only trace of
the missing delegate was a clause in a free-text comment. Exit status and the
agent's own report are the only two signals `agent_run_outcome` consults, and
neither of them can see a delegate.

WHERE THE EVIDENCE COMES FROM, AND WHERE IT DOES NOT. Not from shell text: a
gate built on recognising ``codex exec`` in a command was removed in review of
#896 as unsound (see ``syn_shared.delegation``). The delegate reports itself,
through the platform's ``syn-delegate`` shim, into the workspace's child
journal - a format agentic-workspace owns. This module reads it only through
`DelegationEvidencePort` (in ``orchestration.ports``), already normalised to
`DelegationAttempt`; nothing here knows what a claude or codex transcript looks like.

THE RULE. The workflow schema has one boolean, ``allow_delegation``, and no
notion of an optional delegate, so a declared delegation is REQUIRED: at least
one cross-harness delegate must have reported success. Evidence that cannot be
read is not evidence of success - an unverifiable delegation fails the phase
the same way a missing one does, under its own reason, because "we could not
tell" reading as green is exactly the defect.

Every failure here is a platform-detected fact, never the agent's word, so it
is classified `PLATFORM` like any other (see `failure_account`), and carries
its typed `DelegationFailure` - reason and attempts - which `failure_account`
hands to every sink. It is deliberately NOT a `ReportedFailureReason`: that
enum is "the agent's own word, never an inference".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.aggregate_execution.delegation_failure import (
    DelegationFailureReason,
)
from syn_domain.contexts.orchestration.ports.DelegationEvidencePort import (
    DelegationEvidencePort,
    DelegationEvidenceUnavailableError,
    DelegationOutcome,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.agent_run_outcome import (
    phase_failure,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    DelegationFailedError,
)

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
        AgentExecutionResult,
    )


async def delegation_failure(
    evidence: DelegationEvidencePort | None,
    workspace: ManagedWorkspace | None,
    *,
    phase_id: str,
    allow_delegation: bool,
) -> DelegationFailedError | None:
    """The exception that fails this phase for its delegation, or None.

    Returned rather than raised for the reason `phase_failure` gives: the
    caller owns unwinding through its own teardown.
    """
    if not allow_delegation:
        return None
    if evidence is None or workspace is None:
        return DelegationFailedError(
            phase_id=phase_id,
            reason=DelegationFailureReason.UNVERIFIABLE,
            detail="no delegation evidence source is wired for this workspace",
        )
    try:
        attempts = await evidence.attempts(workspace)
    except DelegationEvidenceUnavailableError as error:
        return DelegationFailedError(
            phase_id=phase_id, reason=DelegationFailureReason.UNVERIFIABLE, detail=str(error)
        )
    if not attempts:
        return DelegationFailedError(
            phase_id=phase_id, reason=DelegationFailureReason.NOT_ATTEMPTED
        )
    if any(attempt.outcome is DelegationOutcome.SUCCEEDED for attempt in attempts):
        return None
    return DelegationFailedError(
        phase_id=phase_id, reason=DelegationFailureReason.FAILED, attempts=attempts
    )


async def completion_failure(
    result: AgentExecutionResult,
    *,
    phase_id: str,
    evidence: DelegationEvidencePort | None,
    workspace: ManagedWorkspace | None,
    allow_delegation: bool,
) -> Exception | None:
    """What ends this phase instead of completing it, or None.

    The run's own outcome first (`phase_failure`); the declared delegate is
    asked only once the run itself may complete, so it never relabels a
    failure the run already had.
    """
    return phase_failure(result, phase_id=phase_id) or await delegation_failure(
        evidence, workspace, phase_id=phase_id, allow_delegation=allow_delegation
    )
