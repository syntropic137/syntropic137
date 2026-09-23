"""Host-owned invocation intent and monotonic lifecycle, separate from billing."""

from __future__ import annotations

from enum import StrEnum

from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    Identifier,
    InventoryModel,
)


class InvocationStatus(StrEnum):
    REGISTERED = "registered"
    LAUNCHED = "launched"
    LAUNCH_FAILED = "launch_failed"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SessionInvocationState(InventoryModel):
    invocation_id: Identifier
    attempt_id: Identifier
    harness: Identifier
    status: InvocationStatus = InvocationStatus.REGISTERED
    native_session_id: Identifier | None = None


def validate_invocation_transition(
    previous: SessionInvocationState | None, successor: SessionInvocationState
) -> None:
    if previous is None:
        if (
            successor.status != InvocationStatus.REGISTERED
            or successor.native_session_id is not None
        ):
            raise ValueError("invocation must be registered before launch or binding")
        return
    _validate_identity(previous, successor)
    _validate_launch_failure(previous, successor)
    if previous == successor:
        return
    if previous.status in (
        InvocationStatus.LAUNCH_FAILED,
        InvocationStatus.COMPLETED,
        InvocationStatus.FAILED,
        InvocationStatus.CANCELLED,
    ):
        # Late identity evidence may arrive after exit, but cannot rewrite the outcome.
        if successor.status != previous.status:
            raise ValueError("invocation outcome is terminal")
    elif (
        previous.status == InvocationStatus.LAUNCHED
        and successor.status == InvocationStatus.REGISTERED
    ):
        raise ValueError("launched invocation cannot return to registered")


def _validate_identity(previous: SessionInvocationState, successor: SessionInvocationState) -> None:
    if (previous.attempt_id, previous.harness) != (successor.attempt_id, successor.harness):
        raise ValueError("invocation identity cannot be rebound to another attempt or harness")
    if (
        previous.native_session_id is not None
        and previous.native_session_id != successor.native_session_id
    ):
        raise ValueError("invocation native identity cannot be rebound")


def _validate_launch_failure(
    previous: SessionInvocationState, successor: SessionInvocationState
) -> None:
    if successor.status == InvocationStatus.LAUNCH_FAILED:
        if previous.status not in (InvocationStatus.REGISTERED, InvocationStatus.LAUNCH_FAILED):
            raise ValueError("observed launch cannot become a failed launch")
        if successor.native_session_id is not None:
            raise ValueError("failed launch cannot have a native identity")
