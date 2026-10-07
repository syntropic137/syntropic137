"""What the scorecard keeps about one execution, and the index that finds it.

Stored as JSON in the projection store, validated on the way back in, so the
shape is declared here once and not at each read.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (  # noqa: TC001 - needed at runtime for Pydantic
    FailureClassification,
)
from syn_domain.contexts.orchestration.slices.scorecard.phase_type import (
    PhaseType,
    phase_type_of,
)


class RunOutcome(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ScorecardPhase(BaseModel):
    """One completed phase of one execution, as PhaseCompleted recorded it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    phase_id: str
    session_id: str | None = None
    success: bool
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    total_tokens: int = 0
    duration_seconds: float = 0.0

    @property
    def phase_type(self) -> PhaseType:
        return phase_type_of(self.phase_id)


class PhaseSession(BaseModel):
    """The agent session a phase ran in, as the run's own events recorded it.

    Kept apart from ``ScorecardPhase`` because a failing phase never emits
    PhaseCompleted: its session is only known from provisioning, start or the
    agent's completion, and without it its tool calls read as unmeasured.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    phase_id: str
    session_id: str


class ScorecardRun(BaseModel):
    """One execution: when it was asked for, ran and ended, and how.

    ``chain`` is every execution in its resume chain, oldest first, ending with
    itself. A run that was resumed carries ``superseded_by``: its chain's
    outcome is decided by the run that superseded it, so it is never counted as
    an outcome itself, though its cost still counts toward its chain.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_id: str
    workflow_id: str = ""
    workflow_name: str = ""
    requested_at: datetime | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    outcome: RunOutcome = RunOutcome.RUNNING
    failure_classification: FailureClassification | None = None
    """Set on failed runs only; a failure recorded before #1357 reads UNCLASSIFIED."""
    chain: tuple[str, ...] = ()
    superseded_by: str | None = None
    phases: tuple[ScorecardPhase, ...] = ()
    phase_sessions: tuple[PhaseSession, ...] = ()
    """The latest recorded session of each phase, one entry per phase id."""

    def session_of(self, phase_id: str) -> str | None:
        return next((s.session_id for s in self.phase_sessions if s.phase_id == phase_id), None)

    def with_phase(self, phase: ScorecardPhase) -> ScorecardRun:
        """This run with ``phase`` recorded once: a redelivered phase replaces itself."""
        kept = tuple(p for p in self.phases if p.phase_id != phase.phase_id)
        return self.model_copy(update={"phases": (*kept, phase)})

    def with_session(self, phase_id: str, session_id: str) -> ScorecardRun:
        kept = tuple(s for s in self.phase_sessions if s.phase_id != phase_id)
        sessions = (*kept, PhaseSession(phase_id=phase_id, session_id=session_id))
        phases = tuple(
            p.model_copy(update={"session_id": session_id})
            if p.phase_id == phase_id and p.session_id is None
            else p
            for p in self.phases
        )
        return self.model_copy(update={"phase_sessions": sessions, "phases": phases})

    @property
    def is_final(self) -> bool:
        return self.superseded_by is None


class DayIndex(BaseModel):
    """The executions that ended on one UTC day, so a window reads only its own days."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_ids: tuple[str, ...] = ()
