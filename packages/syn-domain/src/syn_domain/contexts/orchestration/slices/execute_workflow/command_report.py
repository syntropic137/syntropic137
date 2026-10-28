"""What a command Phase leaves in its artifact output directory (ADR-078 D6, D7).

`commands.json` is the step results plus each step's bounded tail, and
`commands/<name>.log` holds a step's tail when it printed anything: the
collector treats an empty file as a failed artifact, so a silent step gets no
log. The same document is written from the recorded event when a restart lost
the workspace, with `tails_lost` set and no tails, so the verdict survives and
only the output is gone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.orchestration._shared.CommandStepValueObjects import CommandStepResult
from syn_shared.workspace_paths import WORKSPACE_OUTPUT_DIR, WORKSPACE_ROOT

if TYPE_CHECKING:
    from collections.abc import Sequence

_OUTPUT_DIR_REL: Final[str] = WORKSPACE_OUTPUT_DIR.relative_to(WORKSPACE_ROOT).as_posix()

#: The command Phase's primary artifact, relative to the workspace root.
COMMANDS_REPORT_PATH: Final[str] = f"{_OUTPUT_DIR_REL}/commands.json"


class CommandStepReport(CommandStepResult):
    """One step as `commands.json` states it: its recorded result and what it printed."""

    tail: str = ""
    dropped_bytes: int = Field(default=0, ge=0)


class CommandsReport(BaseModel):
    """The whole of `commands.json`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    phase_id: str
    success: bool
    timed_out: bool = False
    tails_lost: bool = False
    """True when the workspace was gone and this was rebuilt from the event (D6)."""
    steps: tuple[CommandStepReport, ...] = ()

    @classmethod
    def from_record(
        cls,
        phase_id: str,
        *,
        success: bool,
        timed_out: bool,
        steps: Sequence[CommandStepResult],
    ) -> CommandsReport:
        """The report a lost workspace leaves: the verdict from the event, no tails."""
        return cls(
            phase_id=phase_id,
            success=success,
            timed_out=timed_out,
            tails_lost=True,
            steps=tuple(CommandStepReport(**step.model_dump()) for step in steps),
        )

    def files(self) -> list[tuple[str, bytes]]:
        """`commands.json` first, then a log per step that printed anything."""
        logs = [
            (f"{_OUTPUT_DIR_REL}/commands/{step.name}.log", step.tail.encode())
            for step in self.steps
            if step.tail
        ]
        return [(COMMANDS_REPORT_PATH, self.model_dump_json(indent=2).encode()), *logs]
