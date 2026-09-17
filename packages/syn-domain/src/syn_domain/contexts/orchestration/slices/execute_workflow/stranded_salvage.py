"""Rescuing a phase whose collection a restart interrupted.

THE GAP THIS CLOSES (#1300, round 3). The salvage in `artifact_recovery` runs
inside `WorkflowExecutionProcessor`, on the COLLECT_ARTIFACTS to-do item. A
restart between the agent finishing and that item running does not resume the
processor: the API's startup reconciliation reaps the workspace containers and
then fails every execution still RUNNING, so the run that this salvage exists
to rescue was the one run the salvage could never reach. The hardened path was
real and production took a different one.

WHAT IT NEEDS, AND WHAT IT DOES NOT. The recovery input is the last thing the
phase's agent said, which the aggregate rebuilds from its own event stream, so
this needs no workspace, no container and no live processor - which is exactly
why it can run on a restart, when all three are gone. It asks the aggregate one
question (`stranded_deliverable`) and never inspects the event stream itself.

WHY IT COMPLETES THE PHASE RATHER THAN JUST STORING SOMETHING. A stored
artifact that no phase record points at is not a deliverable, it is an orphan:
`phases[].artifact_id` is how anything finds it. So the phase is collected and
completed through the aggregate, exactly as the live path would, and comes out
marked `deliverable_recovered` by the same rule. What this does NOT do is
resurrect the execution - the remaining phases have no processor and no
workspace and are not going to run - so the caller still fails it. The phase
survives; the run does not. That asymmetry is the point: before this, both died.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    ArtifactsCollectedCommand,
    CompletePhaseCommand,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.artifact_recovery import (
    RECOVERED_SOURCE_PATH,
    recover_deliverable,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
        ArtifactCollector,
    )

logger = logging.getLogger(__name__)

__all__ = ["SalvagedPhase", "salvage_stranded_phase"]

#: What a recovered artifact is tagged as when nobody is left to say what the
#: phase declared. The phase definitions the aggregate replays carry ordering,
#: not output types, and inventing a type would be a worse answer than the
#: collector's own default for an undeclared one.
_RECOVERED_ARTIFACT_TYPE = "text"


@dataclass(frozen=True)
class SalvagedPhase:
    """What a salvage rescued, for the caller to report."""

    phase_id: str
    phase_name: str
    artifact_id: str


async def salvage_stranded_phase(
    aggregate: WorkflowExecutionAggregate,
    *,
    collector: ArtifactCollector,
) -> SalvagedPhase | None:
    """Store and complete the deliverable of a phase nothing collected.

    Returns what was rescued, or None when there was nothing to rescue - no
    stranded phase, or a stranded phase whose agent said nothing worth keeping.
    None is the ordinary answer and is not an error: most executions a restart
    finds RUNNING were nowhere near finishing a phase.

    The aggregate is left holding the new events and is NOT persisted here, so
    the caller keeps one decision about what to write and when. Calling this
    twice is safe: the first call collects the phase, which is what makes
    `stranded_deliverable` answer None to the second.
    """
    stranded = aggregate.stranded_deliverable
    if stranded is None:
        return None

    recovered = recover_deliverable(
        last_agent_message=stranded.last_agent_message,
        wrote=None,
        title=f"{stranded.phase_name}: {RECOVERED_SOURCE_PATH}",
        # Nobody can look: the workspace was reaped before this runs, so there
        # is no repository to read a branch out of. None says "nothing looked",
        # which is the truth and is not the same as "nothing moved" (#1200).
        work=None,
    )
    if recovered is None:
        return None

    execution_id = aggregate.aggregate_id
    artifact_id = str(uuid4())
    await collector.create_artifact(
        artifact_id=artifact_id,
        workflow_id=aggregate.workflow_id or "",
        phase_id=stranded.phase_id,
        execution_id=execution_id,
        session_id=stranded.session_id,
        artifact_type=_RECOVERED_ARTIFACT_TYPE,
        content=recovered.content,
        title=recovered.title,
        source_path=recovered.source_path,
    )

    aggregate.artifacts_collected(
        ArtifactsCollectedCommand(
            execution_id=execution_id,
            phase_id=stranded.phase_id,
            artifact_ids=[artifact_id],
            first_content_preview=recovered.content,
            session_id=stranded.session_id,
            deliverable_recovered=True,
        )
    )
    aggregate.complete_phase(
        CompletePhaseCommand(
            execution_id=execution_id,
            workflow_id=aggregate.workflow_id or "",
            phase_id=stranded.phase_id,
            session_id=stranded.session_id,
            artifact_id=artifact_id,
            # Zero, and zero is the honest number here. The token counts this
            # phase really spent were recorded on AgentExecutionCompleted and
            # are already in Lane 2; re-reporting a guess at them would double
            # count the run. Duration is unmeasured for the same reason.
            input_tokens=0,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            total_tokens=0,
            duration_seconds=0.0,
        )
    )
    logger.warning(
        "Recovered the deliverable of phase %s (%s) in execution %s from its "
        "transcript: a restart interrupted its collection, and without this "
        "the finished work would have been discarded with the execution (#1300)",
        stranded.phase_id,
        stranded.phase_name,
        execution_id,
    )
    return SalvagedPhase(
        phase_id=stranded.phase_id,
        phase_name=stranded.phase_name,
        artifact_id=artifact_id,
    )
