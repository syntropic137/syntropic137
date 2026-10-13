"""EvalRunScored event (Evals v2)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003

from event_sourcing import DomainEvent, event


@event("EvalRunScored", "v1")
class EvalRunScoredEvent(DomainEvent):
    """A scorer judged one run of the eval. The latest per run is its current score.

    ``verdict`` is a ``Verdict`` value, stored as its string. ``score`` is a
    fraction in [0, 1]; read models show it as an integer 0 to 100.
    """

    eval_id: str
    execution_id: str
    verdict: str
    score: float | None = None
    evidence: str = ""
    scorer: str
    scorer_version: str
    scored_at: datetime
    judge_model: str | None = None
    """The model that judged the run, when a model did (#1788). Absent on
    events recorded before it existed and for a deterministic scorer."""
