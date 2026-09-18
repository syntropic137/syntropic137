"""What a WorkflowFailed event knows about the phase that died (#1262).

A failed phase never gets a PhaseCompleted event, and PhaseCompleted is the
only thing that ever wrote a phase's tokens, duration or artifact. So the
failure event is the sole carrier of those measurements, and this is the one
place its fields are read: the projection asks for a record and applies it,
and never names a key.

That matters because the fields are the whole point of #1262. Six runs and
$52.92 were lost to exit 124 in a single evening; one of them had spent 735
tokens against a 1200-second budget and had stalled, and the others had run
171-377 messages deep and needed a bigger budget. Same exit code, opposite
correct responses, and nothing in the stored record told them apart. A count
that reaches the event and stops before the read model is a count no operator
can see.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syn_domain.contexts.orchestration.slices.get_execution_detail.phase_detail import (
        PhaseDetail,
    )


def _as_int(value: object) -> int:
    """A token count, or 0 when the event carried something that is not one.

    Zero rather than None: a phase whose agent never launched spent nothing,
    and "nothing" is the correct report for it rather than a gap to skip over.
    """
    return value if isinstance(value, int) else 0


def _as_float(value: object) -> float | None:
    """An elapsed time, or None when nothing measured one.

    None and 0.0 are different claims - unmeasured versus finished instantly -
    and collapsing them is what reported every timed-out phase as instant
    (#1036).
    """
    return float(value) if isinstance(value, int | float) else None


def _as_str(value: object) -> str | None:
    """A text field, or None when absent."""
    return value if isinstance(value, str) else None


@dataclass(frozen=True)
class FailedPhaseRecord:
    """The measurements a WorkflowFailed event carries about its failed phase."""

    phase_id: str
    """Which phase died, or "" when the event named none.

    Empty rather than None, and deliberately not a separate "no phase" case:
    a run can fail with nothing in flight, and the caller looks the id up in
    its stored phases either way. An empty id simply matches no phase, so the
    absent case needs no branch anywhere.
    """

    error_message: str | None = None
    observed_branches: list[object] | None = None
    """How this phase's branches stood when it died (#1200), as stored.

    Plain data, not value objects: the store round-trips these and
    ``PhaseExecutionDetail.from_dict`` is the hop that rebuilds them. Carried
    THREE-VALUED - readings, `[]` for "read the workspace and nothing had
    moved", and None for "nothing could look" - because a default of `[]`
    here would report the third as the second.
    """

    artifact_ids: tuple[str, ...] = ()
    """Everything this phase wrote and got to keep (#1321).

    A failed phase used to read artifact_id=None, so the one field an operator
    opens to find a refused phase's deliverable was the one guaranteed empty.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0

    duration_seconds: float | None = None
    """Seconds the phase ran, or None when nothing measured it."""

    failed_at: str | None = None

    @property
    def total_tokens(self) -> int:
        """Summed from the four, never carried as a fifth event field.

        Summing here is what stops the total disagreeing with its parts.
        """
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_tokens
            + self.cache_read_tokens
        )

    @property
    def elapsed_seconds(self) -> float:
        """What this phase adds to the execution's duration total.

        0.0 when unmeasured: a failure with no phase in flight has no time to
        add, and adding nothing is the right answer rather than a reason to
        skip the tokens beside it.
        """
        return self.duration_seconds or 0.0

    @classmethod
    def from_event(cls, event_data: Mapping[str, object]) -> FailedPhaseRecord:
        """Read the failed-phase fields out of a WorkflowFailed payload.

        The payload reaches a projection flattened by ``model_dump()``, so
        every field arrives as plain data of unverified shape. Coercing here
        is what lets every field below state a type the read model can trust.
        """
        artifact_ids = event_data.get("failed_phase_artifact_ids")
        observed = event_data.get("observed_branches")
        return cls(
            phase_id=_as_str(event_data.get("failed_phase_id")) or "",
            error_message=_as_str(event_data.get("error_message")),
            observed_branches=observed if isinstance(observed, list) else None,
            artifact_ids=(
                tuple(a for a in artifact_ids if isinstance(a, str))
                if isinstance(artifact_ids, list)
                else ()
            ),
            input_tokens=_as_int(event_data.get("failed_phase_input_tokens")),
            output_tokens=_as_int(event_data.get("failed_phase_output_tokens")),
            cache_creation_tokens=_as_int(event_data.get("failed_phase_cache_creation_tokens")),
            cache_read_tokens=_as_int(event_data.get("failed_phase_cache_read_tokens")),
            duration_seconds=_as_float(event_data.get("failed_phase_duration_seconds")),
            failed_at=_as_str(event_data.get("failed_at")),
        )

    def stamp_onto(self, phase: PhaseDetail) -> None:
        """Record on ``phase`` everything this failure knows about it.

        The tokens are written unconditionally, zeros included, for the reason
        ``_as_int`` gives. The artifact and the duration are written only when
        the event carried them, so a failure that measured neither leaves what
        the phase already reported rather than overwriting it with a blank.
        """
        phase.status = "failed"
        phase.error_message = self.error_message
        phase.observed_branches = self.observed_branches
        phase.input_tokens = self.input_tokens
        phase.output_tokens = self.output_tokens
        phase.cache_creation_tokens = self.cache_creation_tokens
        phase.cache_read_tokens = self.cache_read_tokens
        phase.total_tokens = self.total_tokens

        # PhaseDetail names one artifact and the primary deliverable is stored
        # first, matching what the success path writes (#1321).
        if self.artifact_ids:
            phase.artifact_id = self.artifact_ids[0]

        # Without this the duration stays at the 0.0 PhaseDetail.running()
        # seeded it with, reporting a timed-out phase as instantaneous (#1036).
        if self.duration_seconds is not None:
            phase.duration_seconds = self.duration_seconds
            phase.completed_at = self.failed_at
