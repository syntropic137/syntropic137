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
`DelegationEvidencePort`, already normalised to `DelegationAttempt`; nothing
here knows what a claude or codex transcript looks like.

THE RULE. The workflow schema has one boolean, ``allow_delegation``, and no
notion of an optional delegate, so a declared delegation is REQUIRED: at least
one cross-harness delegate must have reported success. Evidence that cannot be
read is not evidence of success - an unverifiable delegation fails the phase
the same way a missing one does, under its own reason, because "we could not
tell" reading as green is exactly the defect.

Every failure here is a platform-detected fact, never the agent's word, so it
is raised as an ordinary exception and classified `PLATFORM` like any other
(see `agent_run_outcome`). It is deliberately NOT a `ReportedFailureReason`:
that enum is "the agent's own word, never an inference".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from syn_domain.contexts.agent_sessions.domain.events.DelegationFinishedEvent import (
    DelegationOutcome,
)

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace


@dataclass(frozen=True)
class DelegationAttempt:
    """One delegate the phase's agent launched, as the platform observed it."""

    delegate_id: str
    """The journal's id for this child invocation."""
    target_harness: str
    """Which harness the work was delegated TO (``claude``, ``codex``)."""
    outcome: DelegationOutcome | None
    """How it ended; None when it launched and never reported an end."""
    exit_code: int | None = None
    reason: str | None = None
    """Why it could not launch, when the shim named a reason."""

    def describe(self) -> str:
        ended = self.outcome.value if self.outcome is not None else "never reported an outcome"
        detail = [f"exit_code={self.exit_code}"] if self.exit_code is not None else []
        if self.reason is not None:
            detail.append(f"reason={self.reason}")
        suffix = f" ({', '.join(detail)})" if detail else ""
        return f"delegate {self.delegate_id} -> {self.target_harness}: {ended}{suffix}"


class DelegationEvidenceUnavailableError(Exception):
    """The port could not read the delegation record for this workspace."""


class DelegationEvidencePort(Protocol):
    """Every cross-harness delegation a phase's workspace recorded.

    Satisfied by an adapter over agentic-workspace's child journal. Raises
    `DelegationEvidenceUnavailableError` when the record cannot be read; an
    empty tuple is a positive answer - "read it, nothing delegated".
    """

    async def attempts(self, workspace: ManagedWorkspace) -> tuple[DelegationAttempt, ...]: ...


class DelegationFailureReason(StrEnum):
    """Why a required delegation is counted as not having happened."""

    NOT_ATTEMPTED = "not_attempted"
    """The record was read and holds no delegation at all."""
    FAILED = "failed"
    """Delegates were launched and none of them succeeded."""
    UNVERIFIABLE = "unverifiable"
    """No record could be read, so success cannot be shown."""


class DelegationFailedError(RuntimeError):
    """A phase that declared delegation did not delegate successfully (#894)."""

    def __init__(
        self,
        *,
        phase_id: str,
        reason: DelegationFailureReason,
        attempts: tuple[DelegationAttempt, ...] = (),
        detail: str | None = None,
    ) -> None:
        self.phase_id = phase_id
        self.reason = reason
        self.attempts = attempts
        lines = [
            f"Required delegation failed for phase {phase_id} ({reason.value}): "
            + _summary(reason, detail)
        ]
        lines.extend(f"  - {attempt.describe()}" for attempt in attempts)
        super().__init__("\n".join(lines))


def _summary(reason: DelegationFailureReason, detail: str | None) -> str:
    if reason is DelegationFailureReason.NOT_ATTEMPTED:
        return "the phase declared allow_delegation but no delegate was launched."
    if reason is DelegationFailureReason.FAILED:
        return "every delegate the phase launched failed or never finished."
    return "the delegation record could not be read" + (f": {detail}" if detail else ".")


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
