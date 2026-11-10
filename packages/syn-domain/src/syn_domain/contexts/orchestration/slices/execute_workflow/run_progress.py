"""What a run has already done when its drain begins (#2169, ADR-078 D6).

A drain totals the run from three running lists: each phase's result, every
collected artifact id, and the completed phase ids the next workspace is
built from. A run that starts here begins them empty, a resume with its
inherited prefix. A run picked up mid-way - a green verdict boot collected -
already wrote some of them to its stream, and starting it empty would complete
it as `0` phases with no artifacts and hand its next phase nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    PhaseResult,
    PhaseStatus,
)
from syn_domain.contexts.orchestration.domain.events.ArtifactsCollectedForPhaseEvent import (
    ArtifactsCollectedForPhaseEvent,
)
from syn_domain.contexts.orchestration.domain.events.PhaseCompletedEvent import (
    PhaseCompletedEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.resume_handoff import (
    inherited_phase_ids,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ResumeOrigin,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.run_todo_fold import (
        ExecutionEventStream,
    )


@dataclass
class RunProgress:
    """The drain's running lists, owned by one run and never by the processor."""

    phase_results: list[PhaseResult] = field(default_factory=list)
    artifact_ids: list[str] = field(default_factory=list)
    completed_phase_ids: list[str] = field(default_factory=list)

    @classmethod
    def starting(cls, origin: ResumeOrigin | None) -> RunProgress:
        """A run whose stream holds no phase of its own yet."""
        return cls(completed_phase_ids=inherited_phase_ids(origin))

    @classmethod
    async def read(
        cls, events: ExecutionEventStream, execution_id: str, origin: ResumeOrigin | None
    ) -> RunProgress:
        """A run picked up mid-way, from its own stream: what it already did counts."""
        return cls.from_stream(origin, await events.read(execution_id))

    @classmethod
    def from_stream(cls, origin: ResumeOrigin | None, events: Sequence[object]) -> RunProgress:
        """A run picked up from its stream: what it completed and collected so far.

        The same lists the drain would hold had it never stopped: a result per
        `PhaseCompleted`, every id `ArtifactsCollectedForPhase` stored, in
        stream order, after any inherited prefix.
        """
        progress = cls.starting(origin)
        for event in events:
            if isinstance(event, ArtifactsCollectedForPhaseEvent):
                progress.artifact_ids.extend(
                    i for i in event.artifact_ids if i not in progress.artifact_ids
                )
            elif isinstance(event, PhaseCompletedEvent):
                progress.phase_results.append(_result_of(event))
                if event.phase_id not in progress.completed_phase_ids:
                    progress.completed_phase_ids.append(event.phase_id)
        return progress


def _result_of(event: PhaseCompletedEvent) -> PhaseResult:
    return PhaseResult(
        phase_id=event.phase_id,
        status=PhaseStatus.COMPLETED if event.success else PhaseStatus.FAILED,
        completed_at=event.completed_at,
        artifact_id=event.artifact_id,
        session_id=event.session_id,
        input_tokens=event.input_tokens,
        output_tokens=event.output_tokens,
        cache_creation_tokens=event.cache_creation_tokens,
        cache_read_tokens=event.cache_read_tokens,
        total_tokens=event.total_tokens,
        error_message=event.error_message,
    )
