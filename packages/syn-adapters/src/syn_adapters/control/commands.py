"""Control plane command definitions.

These are the commands that can be sent to control execution flow.
Pure data classes with no behavior - domain logic is in controller.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal


class ControlSignalType(StrEnum):
    """Types of control signals."""

    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"
    INJECT = "inject"


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
    """Result of handling a control command."""

    success: bool
    execution_id: str
    new_state: str
    message: str | None = None
    error: str | None = None
