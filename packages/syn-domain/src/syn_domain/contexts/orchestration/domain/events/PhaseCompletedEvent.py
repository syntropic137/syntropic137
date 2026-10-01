"""PhaseCompleted event - emitted when a phase completes execution."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic
from typing import Any

from event_sourcing import DomainEvent, event

# Runtime import needed for the Pydantic field type (noqa: TC001)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    SideEffectStatus,  # noqa: TC001 - needed at runtime for Pydantic
)


@event("PhaseCompleted", "v1")
class PhaseCompletedEvent(DomainEvent):
    """Event emitted when a phase completes execution.

    Contains the results of the phase including artifact and metrics.
    Cost is Lane 2 telemetry — see execution_cost / session_cost projections.
    """

    workflow_id: str
    execution_id: str
    phase_id: str
    completed_at: datetime

    # Outcome
    success: bool
    error_message: str | None = None

    # Results
    artifact_id: str | None = None
    session_id: str | None = None

    #: True when this phase's deliverable was recovered from the session
    #: transcript instead of being written to `artifacts/output/`.
    #:
    #: A salvaged phase COMPLETES - discarding a finished run over a missing
    #: report is the cost #1300 measured - but a phase that completed while
    #: its declared contract was broken must not be indistinguishable from one
    #: that honoured it. Without this field it was: a salvaged phase's
    #: PhaseCompleted was byte-for-byte a clean phase's, so neither an
    #: operator reading one execution nor anyone counting across many could
    #: tell how often the salvage was firing or which runs stood on it.
    deliverable_recovered: bool = False

    #: What the phase said happened to its external writes - `denied` for a
    #: refused PR comment beside a finished deliverable. None when the phase
    #: said nothing, which includes every event written before this field.
    reported_side_effects: SideEffectStatus | None = None

    # Metrics (tokens only — cost lives in Lane 2)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    total_tokens: int = 0
    duration_seconds: float = 0.0

    # Additional metadata
    metadata: dict[str, Any] | None = None
