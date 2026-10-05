"""Why a phase that declared delegation is recorded as not having delegated (#894).

A value object rather than prose in ``error``: the reason and the delegates
the platform observed are what an operator acts on - a delegate that never
launched and a delegate that launched and failed are different incidents -
and a client cannot select between them by parsing a sentence. Carried from
the failure command through `WorkflowFailedEvent` to the execution detail
read model and its API response, unchanged at every hop.

It is a platform-observed fact, never the agent's word, which is why it is a
field of its own and not a `ReportedFailureReason`.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

# Runtime import: a pydantic field type.
from syn_domain.contexts.agent_sessions import DelegationOutcome  # noqa: TC001


class DelegationFailureReason(StrEnum):
    """Why a required delegation is counted as not having happened."""

    NOT_ATTEMPTED = "not_attempted"
    """The record was read and holds no delegation at all."""
    FAILED = "failed"
    """Delegates were launched and none of them succeeded."""
    UNVERIFIABLE = "unverifiable"
    """No record could be read, so success cannot be shown."""


class DelegationAttempt(BaseModel):
    """One delegate the phase's agent launched, as the platform observed it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

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


class DelegationFailure(BaseModel):
    """The typed account of a failed required delegation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: DelegationFailureReason
    attempts: tuple[DelegationAttempt, ...] = ()
    """Every cross-harness delegate the record held; empty for `not_attempted`
    and `unverifiable`."""
    detail: str | None = None
    """Why the record could not be read, for `unverifiable`."""

    @classmethod
    def from_stored(cls, value: object) -> DelegationFailure | None:
        """The stored account, `None` for a failure that recorded none.

        Every row and event written before #894 has no such key, and replays
        as `None` rather than raising.
        """
        return None if value is None else cls.model_validate(value)
