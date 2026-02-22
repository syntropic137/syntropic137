"""Execution state machine.

Manages valid state transitions for execution control.
Pure logic - no I/O dependencies.
"""

from __future__ import annotations

from enum import Enum


class ExecutionState(str, Enum):
    """Possible execution states."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


# Valid transitions: from_state -> set of valid to_states
VALID_TRANSITIONS: dict[ExecutionState, set[ExecutionState]] = {
    ExecutionState.PENDING: {ExecutionState.RUNNING, ExecutionState.CANCELLED},
    ExecutionState.RUNNING: {
        ExecutionState.PAUSED,
        ExecutionState.CANCELLED,
        ExecutionState.COMPLETED,
        ExecutionState.FAILED,
        ExecutionState.INTERRUPTED,
    },
    ExecutionState.PAUSED: {
        ExecutionState.RUNNING,
        ExecutionState.CANCELLED,
        ExecutionState.INTERRUPTED,
    },
    ExecutionState.CANCELLED: set(),  # Terminal state
    ExecutionState.COMPLETED: set(),  # Terminal state
    ExecutionState.FAILED: set(),  # Terminal state
    ExecutionState.INTERRUPTED: set(),  # Terminal state
}


class ExecutionStateMachine:
    """State machine for execution control."""

    def __init__(self, initial_state: ExecutionState = ExecutionState.PENDING) -> None:
        self._state = initial_state

    @property
    def state(self) -> ExecutionState:
        return self._state

    @property
    def is_terminal(self) -> bool:
        return self._state in {
            ExecutionState.CANCELLED,
            ExecutionState.COMPLETED,
            ExecutionState.FAILED,
            ExecutionState.INTERRUPTED,
        }

    def can_transition_to(self, target: ExecutionState) -> bool:
        """Check if transition to target state is valid."""
        return target in VALID_TRANSITIONS.get(self._state, set())

    def can_pause(self) -> bool:
        return self.can_transition_to(ExecutionState.PAUSED)

    def can_resume(self) -> bool:
        return self._state == ExecutionState.PAUSED

    def can_cancel(self) -> bool:
        return self.can_transition_to(ExecutionState.CANCELLED)

    def transition(self, target: ExecutionState) -> ExecutionState:
        """Transition to target state. Raises if invalid."""
        if not self.can_transition_to(target):
            raise InvalidTransitionError(f"Cannot transition from {self._state} to {target}")
        self._state = target
        return self._state


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""

    pass
