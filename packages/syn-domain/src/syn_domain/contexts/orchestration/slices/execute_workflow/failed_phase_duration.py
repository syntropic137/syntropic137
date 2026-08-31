"""How long a phase ran before it failed (#1036).

A phase that fails never reaches `_handle_complete_phase`, so nothing on the
success path computes its duration and it reports 0.0 downstream. That is the
least plausible value available: a phase killed at its timeout ran for exactly
its budget, and 0.0 points a reader at provisioning rather than at the limit.

Extracted rather than inlined because `WorkflowExecutionProcessor` is already
over its file-size threshold and carries an exception for it; adding to it
pushed the file past what that exception allows. Growing an excepted file is how
an exception becomes permanent.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

if TYPE_CHECKING:
    from datetime import datetime as DateTime

    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        PhaseResult,
    )


def failed_phase_elapsed_seconds(
    started_at: DateTime | None,
    *,
    now: DateTime | None = None,
) -> float | None:
    """Seconds a failed phase ran, or None when it never started.

    None and 0.0 mean different things and must stay distinguishable: None is
    "this phase never began, so there is no duration to report", while 0.0 would
    claim it began and took no time. Callers persist None as absent rather than
    coercing it.
    """
    if started_at is None:
        return None
    return ((now or datetime.now(UTC)) - started_at).total_seconds()


def failed_phase_outcome(
    phase_id: str | None,
    started_at_by_phase: Mapping[str, DateTime],
    session_id_by_phase: Mapping[str, str],
    error_message: str,
) -> tuple[float | None, PhaseResult | None]:
    """The duration and result for a phase that failed.

    One call rather than three lookups at the call site: the processor is over
    its file-size threshold, and the caller does not need to know that "how long
    did it run" and "what result does it produce" share a start timestamp.
    """
    started_at = started_at_by_phase.get(phase_id) if phase_id else None
    return (
        failed_phase_elapsed_seconds(started_at),
        failed_phase_result(
            phase_id,
            started_at,
            session_id_by_phase.get(phase_id or "", ""),
            error_message,
        ),
    )


def failed_phase_result(
    phase_id: str | None,
    started_at: DateTime | None,
    session_id: str,
    error_message: str,
) -> PhaseResult | None:
    """The `PhaseResult` for a phase that failed, or None if it never started.

    A phase with no recorded start produces no result: inventing one would put a
    phase into the execution's results that never ran.
    """
    if phase_id is None or started_at is None:
        return None

    from syn_domain.contexts.orchestration.slices.execute_workflow.PhaseResultBuilder import (
        PhaseResultBuilder,
    )

    return PhaseResultBuilder.failure(
        phase_id=phase_id,
        started_at=started_at,
        session_id=session_id,
        error_message=error_message,
    )
