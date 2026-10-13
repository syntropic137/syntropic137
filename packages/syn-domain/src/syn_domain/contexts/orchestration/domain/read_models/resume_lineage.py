"""Resume lineage: which execution a run resumed, and which run resumed it (#1881).

Both directions are already recorded, one on each stream: the child's
`WorkflowExecutionStarted.resumed_from` names its parent, and the parent's own
`ExecutionResumed` names its child. The read models project each from its own
event, so neither side has to join the other's stream to know it.

A parent admits a resume at most once (`resume_rules`), so a chain is a linked
list: one parent, at most one child.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.aggregate_execution.legacy_event_shapes import (
    resumed_event_applies,
    upcast_forked_payload,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ResumeOrigin,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionResumedEvent import (
    ExecutionResumedEvent,
)

if TYPE_CHECKING:
    from pydantic import JsonValue


@dataclass(frozen=True)
class ResumedFrom:
    """The execution a resumed run continues, and the phase it picked up at."""

    parent_execution_id: str
    resume_phase_id: str

    @classmethod
    def of_started(cls, resumed_from: JsonValue) -> ResumedFrom | None:
        """Read off a stored `WorkflowExecutionStarted.resumed_from`. None for a fresh run."""
        if resumed_from is None:
            return None
        origin = ResumeOrigin.model_validate(resumed_from)
        return cls(origin.parent_execution_id, origin.resume_phase_id)

    @classmethod
    def from_stored(cls, raw: object) -> ResumedFrom | None:
        """Read back what `to_stored` wrote. A row from before #1881 has none."""
        if not isinstance(raw, Mapping):
            return None
        parent = raw.get("parent_execution_id")
        phase = raw.get("resume_phase_id")
        if not isinstance(parent, str) or not isinstance(phase, str):
            return None
        return cls(parent, phase)

    def to_stored(self) -> dict[str, str]:
        return {
            "parent_execution_id": self.parent_execution_id,
            "resume_phase_id": self.resume_phase_id,
        }


def admitted_resume(stored: object) -> ExecutionResumedEvent:
    """A stored pre-rename `ExecutionForked` payload as the `ExecutionResumed` it always was.

    Upcast the way the aggregate upcasts it, so a resume recorded before the
    rename links forward like any other.
    """
    return ExecutionResumedEvent.model_validate(upcast_forked_payload(stored))


def resume_to_link(stored: object) -> ExecutionResumedEvent | None:
    """A stored `ExecutionResumed` as the resume to link forward, or None.

    None for a pre-rename un-pause, which the store admits as a generic event
    (`replays_generic`) and which names no child: it is skipped, loudly, so a
    rebuild advances past it. The shape is decided by `resumed_event_applies`,
    the same gate the aggregate uses; an ambiguous payload raises there and
    fails the projection rather than being guessed at.
    """
    execution_id = stored.get("execution_id") if isinstance(stored, Mapping) else None
    if not resumed_event_applies(stored, execution_id):
        return None
    return ExecutionResumedEvent.model_validate(stored)
