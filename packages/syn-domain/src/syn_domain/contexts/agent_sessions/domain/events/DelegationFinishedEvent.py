"""DelegationFinished event - a delegated child run ended (issue #895).

Records the DELEGATE's own outcome, not the enclosing shell's. That
distinction is the whole of #894: a phase reported success because the shell
exited zero while the delegation it declared never happened, and the agent
narrated a hypothetical result the platform then recorded as a success.
"""

from __future__ import annotations

from enum import StrEnum

from event_sourcing import DomainEvent, event
from pydantic import field_validator


class DelegationOutcome(StrEnum):
    """How a delegated run ended, in provider-neutral terms.

    WHY NOT A BARE EXIT CODE (raised in review of this event): an integer exit
    status is shell-specific baggage. The native same-harness fan-out path
    reports a boolean success and has no process to exit; cancellation and
    timeout have no natural integer either. Since these events are v1 and this
    repo has no upcaster framework, encoding a shell assumption now would need
    a v2 to undo.
    """

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


@event("DelegationFinished", "v1")
class DelegationFinishedEvent(DomainEvent):
    """A delegated child run ended.

    WHAT THIS MODEL GUARANTEES: the attempt id is non-blank and the outcome is
    one of the values above. It does not verify that the attempt was ever
    started, nor that it finished only once.
    """

    delegation_attempt_id: str

    outcome: DelegationOutcome
    """Provider-neutral. Applies equally to a shell delegate, a native
    subagent, and a run that was cancelled or timed out."""

    native_exit_code: int | None = None
    """The delegate's own process exit code where one exists.

    Optional because not every delegation route has a process: native
    same-harness fan-out does not. Carried alongside the outcome rather than
    instead of it, so the shell case keeps its detail without every other case
    having to invent one.
    """

    @field_validator("delegation_attempt_id")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        if not value.strip():
            msg = "identifier must not be blank"
            raise ValueError(msg)
        return value
