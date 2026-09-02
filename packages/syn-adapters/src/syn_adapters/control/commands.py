"""Control plane command definitions.

These are the commands that can be sent to control execution flow.
Pure data classes with no behavior - domain logic is in controller.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

# Re-exported, not defined here. The enum moved to syn_shared so that domain
# slice code can compare against it without importing the adapter layer
# (issue #817 / VSA206). This name stays importable from here so existing
# adapter call sites are unaffected, and there is still exactly one definition.
from syn_shared.control import ControlSignalType

__all__ = [
    "CancelExecution",
    "ControlCommand",
    "ControlResult",
    "ControlSignal",
    "ControlSignalType",
    "InjectContext",
    "PauseExecution",
    "ResumeExecution",
]


@dataclass(frozen=True)
class PauseExecution:
    """Command to pause an execution at the next yield point."""

    execution_id: str
    reason: str | None = None
    requested_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class ResumeExecution:
    """Command to resume a paused execution."""

    execution_id: str
    requested_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class CancelExecution:
    """Command to cancel an execution with cleanup."""

    execution_id: str
    reason: str | None = None
    requested_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class InjectContext:
    """Command to inject a message into agent context."""

    execution_id: str
    message: str
    role: Literal["user", "system"] = "user"
    requested_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# Union type for all commands
ControlCommand = PauseExecution | ResumeExecution | CancelExecution | InjectContext


@dataclass(frozen=True)
class ControlSignal:
    """Signal to be checked by executor at yield points."""

    signal_type: ControlSignalType
    execution_id: str
    reason: str | None = None
    inject_message: str | None = None


@dataclass(frozen=True)
class ControlResult:
    """Result of handling a control command.

    `new_state` is read from the projection *before* any control signal is
    enqueued - cancel/pause/resume are asynchronous, so this handler never
    observes the transition it requested. `state_pending` says whether
    `new_state` is that pre-signal read (True: a transition may still be in
    flight and has not been confirmed) or the actual current state because
    no signal was queued at all (False, e.g. the command was rejected, or
    the command - like inject - never changes state) (#1062).
    """

    success: bool
    execution_id: str
    new_state: str
    message: str | None = None
    error: str | None = None
    state_pending: bool = False
