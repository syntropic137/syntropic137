"""The rules for starting the execution a resume admitted (ADR-014 s7, #1454).

`resume_rules` decides, on the PARENT, whether it may be resumed. This is the
second half: turning that decision into the CHILD's start, and refusing to
start a child whose inherited work does not match what it would run.

Both halves are pure functions of replayed state, for the reason `resume_rules`
gives: the aggregate keeps the guard and raises, the rule is testable without
building one.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.aggregate_execution.branch_continuation import (
    continuation_candidates,
    decide_continuation,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    StartResumeCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.start_pins import (
    ResumeOrigin,
    phase_definitions_of,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.branch_continuation import (
        LeftBranches,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.start_pins import (
        AdmittedResume,
        StartPins,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
        WorkflowExecutionStartedEvent,
    )

logger = logging.getLogger(__name__)


def refuse_resume_start(command: StartResumeCommand) -> str | None:
    """Why this resume may not start from this snapshot, or None if it may.

    The snapshot is the PARENT's pinned phase config, and the inherited prefix
    was decided against the parent's phase list. If the two disagree the child
    would hand its resumed phase outputs from phases it does not have, or skip
    a phase it does - so it refuses rather than guesses (#1454):

    * no snapshot at all - the parent started before phases were pinned, and
      the only other source is the template, which may have been edited since;
    * an inherited phase absent from the snapshot;
    * a resume phase absent from the snapshot;
    * inherited phases that are not exactly the snapshot's phases before the
      resume phase, in order - a gap would run nothing for a phase the resumed
      one may read. A phase the parent's certified review skipped is not a gap
      (#1681): it was never going to run, so it is passed over here as the
      parent's prefix passed over it.
    """
    resume_execution_id = command.aggregate_id
    pinned_phases = command.pinned_phases
    resumed_from = command.resumed_from
    if not pinned_phases:
        return (
            f"Cannot start resume {resume_execution_id}: its parent "
            f"{resumed_from.parent_execution_id} recorded no pinned phase config, so what "
            "the resume would run can only be read from the current workflow template (#1454)"
        )
    pinned_ids = [p.phase_id for p in sorted(pinned_phases, key=lambda p: p.order)]
    inherited_ids = [p.phase_id for p in resumed_from.inherited_phases]
    absent = [phase_id for phase_id in inherited_ids if phase_id not in pinned_ids]
    if absent:
        return (
            f"Cannot start resume {resume_execution_id}: inherited phase(s) {absent} are "
            "absent from the pinned phase config"
        )
    resume = resumed_from.resume_phase_id
    if resume not in pinned_ids:
        return (
            f"Cannot start resume {resume_execution_id}: resume phase {resume!r} is absent "
            "from the pinned phase config"
        )
    skipped = set(command.inherited_skipped_phase_ids)
    before_resume = [p for p in pinned_ids[: pinned_ids.index(resume)] if p not in skipped]
    if inherited_ids != before_resume:
        return (
            f"Cannot start resume {resume_execution_id}: inherited phases {inherited_ids} are "
            f"not the pinned phases before {resume!r}, {before_resume}"
        )
    return None


def resume_start_command(
    *,
    parent_execution_id: str | None,
    workflow_id: str,
    workflow_name: str,
    pins: StartPins,
    resumed: bool,
    admitted: AdmittedResume,
    left: LeftBranches,
) -> StartResumeCommand:
    """The child's start, built from the parent's replayed stream alone.

    Raises when the parent has not admitted a resume, or when the resume it
    admitted cannot be named - under ADR-023 the child's id can replay as
    None, and a start with no id to start is refused, not invented.

    Everything the child runs comes from here: the parent's inputs, its pinned
    phases and its commits. Nothing is read from the workflow template.

    ``left`` is what the parent's failing phase left on origin; when the resume
    resumes that phase, those branches are its continuation candidates (#1513).
    """
    if parent_execution_id is None or not resumed:
        msg = f"Execution {parent_execution_id} has not admitted a resume"
        raise ValueError(msg)
    resume_execution_id, resume_phase_id = admitted.resume_execution_id, admitted.resume_phase_id
    if not resume_execution_id or not resume_phase_id:
        msg = f"Execution {parent_execution_id} admitted a resume its stream cannot name"
        raise ValueError(msg)
    # An `ExecutionResumed` written before #1462 names no owner for its phases,
    # and one recorded on a resume's CHILD is exactly the admission that bug left
    # unstartable: its inherited phases are owned further up. This stream knows
    # who by its own `resumed_from`, so the start names them rather than falling
    # back to this execution, which holds none of their artifacts.
    owners = {} if pins.resumed_from is None else pins.resumed_from.owners()
    inherited = [
        p
        if p.origin_execution_id
        else p.model_copy(
            update={"origin_execution_id": owners.get(p.phase_id, parent_execution_id)}
        )
        for p in admitted.inherited_phases
    ]
    return StartResumeCommand(
        execution_id=resume_execution_id,
        workflow_id=workflow_id,
        workflow_name=workflow_name,
        inputs=dict(pins.inputs),
        pinned_phases=list(pins.pinned_phases),
        source_commits=list(pins.source_commits),
        resumed_from=ResumeOrigin(
            parent_execution_id=parent_execution_id,
            inherited_phases=inherited,
            resume_phase_id=resume_phase_id,
        ),
        continuation_candidates=continuation_candidates(left, resume_phase_id),
        inherited_skipped_phase_ids=list(admitted.inherited_skipped_phase_ids),
        workflow_version=pins.workflow_version,
    )


def resume_started_event(command: StartResumeCommand) -> WorkflowExecutionStartedEvent:
    """The child's own `WorkflowExecutionStarted`, once `refuse_resume_start` passed.

    The same event a fresh run starts with, so every read model that knows how
    to show a run knows how to show this one. Its phase list is the pinned
    snapshot's, not the template's, and `resumed_from` is what marks it a resume.

    It also records which branches the resumed phase continues and which it
    abandoned, decided here from the candidates and what the forge said about
    them (#1513). An abandoned branch is a warning, logged and on the event.
    """
    from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
        WorkflowExecutionStartedEvent,
    )

    continued, abandoned = decide_continuation(
        command.continuation_candidates, command.remote_branches
    )
    for branch in abandoned:
        logger.warning(
            "Resume %s starts %s fresh instead of continuing %s: %s",
            command.aggregate_id,
            branch.repository,
            branch.branch,
            branch.reason,
        )
    return WorkflowExecutionStartedEvent(
        workflow_id=command.workflow_id,
        execution_id=command.aggregate_id,
        workflow_name=command.workflow_name,
        started_at=datetime.now(UTC),
        total_phases=len(command.pinned_phases),
        inputs=command.inputs,
        phase_definitions=[asdict(d) for d in phase_definitions_of(command.pinned_phases)],
        pinned_phases=command.pinned_phases,
        source_commits=command.source_commits,
        resumed_from=command.resumed_from,
        continued_branches=continued or None,
        abandoned_branches=abandoned or None,
        inherited_skipped_phase_ids=command.inherited_skipped_phase_ids or None,
        workflow_version=command.workflow_version,
    )
