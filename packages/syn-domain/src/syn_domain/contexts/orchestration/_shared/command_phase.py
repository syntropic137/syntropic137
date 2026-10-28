"""What a Phase runs: an agent, or the author's fixed shell steps (ADR-078 D1).

Every Phase used to run an LLM agent, so a Phase whose whole job is
``cargo build`` paid a model to type it and wait. A command Phase runs an
ordered list of author-written steps instead, at 0 tokens.

These live in ``_shared`` because both the template's ``PhaseDefinition`` and
the execution's pinned ``ExecutablePhase`` carry them, and a domain event may
import from here but not from an aggregate's internals.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: A step's name names its log artifact (``commands/<name>.log``), so it is a
#: file-name-safe slug, never a path.
COMMAND_STEP_NAME_PATTERN = r"^[a-z0-9][a-z0-9-]{0,62}$"

#: Every timeout is a positive integer (ADR-078 D4). Zero would reach Docker as
#: "no timeout" and fall back to the workspace default; strict refuses ``1.5``
#: and ``"60"`` rather than coercing them into something the author did not write.
PositiveSeconds = Annotated[int, Field(strict=True, gt=0)]


class PhaseKind(StrEnum):
    """What runs a Phase. A Phase that declares nothing is an agent Phase (ADR-069 D4)."""

    AGENT = "agent"
    COMMAND = "command"


class CommandStep(BaseModel):
    """One fixed shell step of a command Phase (ADR-078 D1).

    ``run`` is executed as ``sh -c <run>`` in ``/workspace``. It is never
    templated: substituting execution inputs into a shell line is an
    injection path, so v1 passes no inputs to a step at all.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(..., pattern=COMMAND_STEP_NAME_PATTERN)
    run: str = Field(..., min_length=1)
    timeout_seconds: PositiveSeconds | None = None
    """This step's own bound. None: whatever remains of the Phase's budget."""
    allow_failure: bool = False
    """Record a non-zero exit or this step's own timeout and carry on. Never
    excuses the Phase's deadline."""


class InconsistentPhaseKindError(ValueError):
    """A Phase declared a field its kind does not apply (ADR-078 D2, ADR-069 D5)."""

    def __init__(self, phase_id: str, kind: PhaseKind, problem: str) -> None:
        super().__init__(f"Phase '{phase_id}' (kind: {kind}): {problem}")


def require_unique_step_names(phase_id: str, steps: tuple[CommandStep, ...]) -> None:
    """Refuse two steps with one name: each names its own log artifact."""
    seen: set[str] = set()
    for step in steps:
        if step.name in seen:
            raise InconsistentPhaseKindError(
                phase_id, PhaseKind.COMMAND, f"command step name '{step.name}' is used twice"
            )
        seen.add(step.name)


def stored_phase_kind(stored: object) -> PhaseKind:
    """A phase's kind as a projection stored it; ``agent`` when it predates kinds."""
    return PhaseKind.AGENT if stored is None else PhaseKind(str(stored))


def stored_command_steps(stored: object) -> tuple[CommandStep, ...]:
    """A phase's command steps as a projection stored them; none when it predates kinds."""
    if not isinstance(stored, list):
        return ()
    return tuple(CommandStep.model_validate(step) for step in stored)


#: How much of a step's combined output is retained: what a person reads to see
#: why a build failed, not a log store (ADR-078 D3).
COMMAND_TAIL_BYTES = 8 * 1024


class CommandTerminal(StrEnum):
    """How a bounded command ended. Never folded into the exit code (ADR-078 D3).

    A provider timeout and an explicit ``exit 124`` are different facts, and a
    gate that cannot tell them apart cannot say which one stopped the build.
    """

    EXITED = "exited"
    TIMED_OUT = "timed_out"
    INTERRUPTED = "interrupted"
    FAILED_TO_START = "failed_to_start"


class BoundedCommandResult(BaseModel):
    """What ``run_bounded`` returns: a typed end, and only a bounded tail of output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    terminal: CommandTerminal
    exit_code: int | None = None
    """Set only when ``terminal`` is ``exited``."""
    duration_ms: int = Field(..., ge=0)
    tail: str = ""
    """The last ``tail_bytes`` of combined stdout+stderr, credentials withheld."""
    dropped_bytes: int = Field(default=0, ge=0)
    """Output not retained: older than the tail, or lost before it was read."""

    @model_validator(mode="after")
    def _exit_code_only_when_exited(self) -> BoundedCommandResult:
        if (self.exit_code is not None) != (self.terminal is CommandTerminal.EXITED):
            msg = f"exit_code is set iff terminal is exited, got {self.terminal}/{self.exit_code}"
            raise ValueError(msg)
        return self


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
