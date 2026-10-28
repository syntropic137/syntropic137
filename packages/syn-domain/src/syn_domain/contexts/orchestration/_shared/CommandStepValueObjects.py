"""What one step of a command Phase recorded (ADR-078 D5).

Its own value-object module so the `PhaseCommandsCompleted` event, which may
import only value objects, can carry it.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

#: A step's name names its log artifact (``commands/<name>.log``), so it is a
#: file-name-safe slug, never a path.
COMMAND_STEP_NAME_PATTERN = r"^[a-z0-9][a-z0-9-]{0,62}$"


class CommandStepOutcome(StrEnum):
    """How one step of a command Phase ended, as the Lane 1 record states it (ADR-078 D5)."""

    PASSED = "passed"
    FAILED = "failed"
    """Exited non-zero."""
    TIMED_OUT = "timed_out"
    """Hit its own timeout, or the Phase's deadline, while running."""
    SKIPPED = "skipped"
    """Never started: an earlier step stopped the Phase, or no budget was left."""
    INTERRUPTED = "interrupted"
    """Cancelled while running."""
    FAILED_TO_START = "failed_to_start"
    """The platform could not run it: an exec error or a lost workspace."""


class CommandStepResult(BaseModel):
    """One step's recorded result: the gate's verdict, never its output (ADR-078 D5).

    The exit code and timing are here so a restart that loses the workspace
    loses only the output tails, never what the gate said (D6).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(..., pattern=COMMAND_STEP_NAME_PATTERN)
    outcome: CommandStepOutcome
    exit_code: int | None = None
    duration_ms: int = Field(default=0, ge=0)
    allow_failure: bool = False

    @property
    def stops_the_phase(self) -> bool:
        """Whether this step, as recorded, fails its Phase (D4).

        ``allow_failure`` excuses an exit code and a step's own timeout. A step
        the platform could not start or that was cancelled is never excused:
        neither is the author's step saying no.
        """
        if self.outcome in (CommandStepOutcome.PASSED, CommandStepOutcome.SKIPPED):
            return False
        if self.outcome in (CommandStepOutcome.FAILED, CommandStepOutcome.TIMED_OUT):
            return not self.allow_failure
        return True
