"""Summarise what a phase was doing when it ended (#1262).

A phase killed on its deadline and a phase that hung both exit 124. The
execution record carried nothing that separated them, so an operator deciding
between "the budget was too short, dispatch a continuation" and "it stalled,
do not pay for it again" had to read the transcript - and four runs in one day
were triaged without one.

Everything needed to separate them was already being recorded. The Lane 2
timeline writes each tool call and each git push as its line arrives, so it
survives a SIGKILL intact; the budget is already stated on
``WorkflowExecutionStarted``. None of it reached the read path. This module is
the one place that turns those into the readings ``PhaseActivityInfo``
describes, so no caller has to know which rows count as a push, how a call's
two rows fold into one, or which instant "the end of the phase" is.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_adapters.projections.session_tools import call_identity
from syn_api.types import PhaseActivityInfo
from syn_shared.display import resolve_duration_seconds
from syn_shared.events import GIT_PUSH

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from syn_adapters.projections.session_tools import TimelineRow
    from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
        PhaseExecutionDetail,
    )

#: Timeline rows that record a push, in every spelling one can arrive under.
#:
#: ``git_push`` is the canonical type and the only one ``syn_shared.events``
#: declares. The other two are the legacy hook names, which
#: ``syn_collector.events.types`` keeps deliberately ("kept for backward compat
#: with old hook events already in DB") and whose hook parser still maps both,
#: so a session's timeline can hand us either. Matching only the canonical one
#: would report "no push observed" for a session recorded under a legacy name -
#: wrong in the expensive direction, because no push reads as a stall and a
#: stall is the verdict that says stop paying.
#:
#: They are spelled here rather than imported because syn-collector does not
#: export them as shared vocabulary, and syn-api taking a dependency on the
#: collector to read three strings would be the larger mistake.
_PUSH_OPERATION_TYPES: frozenset[str] = frozenset(
    {GIT_PUSH, "git_push_started", "git_push_completed"},
)


def _last_push_at(operations: Sequence[TimelineRow]) -> datetime | None:
    """When the phase last pushed, or ``None`` if no push was observed.

    ``max`` rather than "the last row": the timeline is queried in ``time``
    order today, and a summary that silently depends on that would report the
    wrong instant the day some caller sorts it differently. A push row with no
    timestamp dates nothing and is skipped rather than defaulted.
    """
    pushes = [
        op.timestamp
        for op in operations
        if op.operation_type in _PUSH_OPERATION_TYPES and op.timestamp is not None
    ]
    return max(pushes) if pushes else None


def summarize_phase_activity(
    phase: PhaseExecutionDetail,
    operations: Sequence[TimelineRow],
    *,
    elapsed_seconds: float | None,
) -> PhaseActivityInfo:
    """The readings that tell a phase killed on its cap from one that hung.

    ``elapsed_seconds`` is passed in, already resolved, rather than derived
    here: the phase reports the same number as ``duration_seconds`` one level
    up, and two derivations of one measurement are two things to keep in
    agreement.
    """
    last_push = _last_push_at(operations)

    return PhaseActivityInfo(
        # Calls, not rows: a call is a start row and a completion row, so the
        # length of `operations` is about double the work (#1061).
        operations_count=len({call_identity(op) for op in operations}),
        last_push_at=last_push,
        # The same call that resolves the phase's own elapsed time, asked to
        # measure from the push instead of the start. That is what makes the
        # two numbers agree about where the phase ENDED: still in flight and
        # the silence grows against the wall clock, finished and it is frozen
        # at the completion. Deciding that here a second time would be a
        # second copy of a rule six surfaces already disagreed about once.
        seconds_since_last_push=resolve_duration_seconds(
            phase.status,
            started_at=last_push,
            completed_at=phase.completed_at,
        ),
        elapsed_seconds=elapsed_seconds,
        timeout_seconds=phase.timeout_seconds,
    )
