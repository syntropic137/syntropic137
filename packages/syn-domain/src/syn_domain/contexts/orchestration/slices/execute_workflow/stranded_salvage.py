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

A COMMAND PHASE HAS NO TRANSCRIPT (#2169). Its verdict is the
`PhaseCommandsCompleted` it recorded, so it is collected the way the live path
collects one whose workspace is gone (ADR-078 D6): `commands.json` rebuilt from
the event with `tails_lost`, through `collect_recorded_commands`, which both
paths call. Collection then rules as it always does (D5): a red gate fails the
execution as `gate` right there, and a green one completes the phase.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from syn_domain.contexts.artifacts import AgentIdentity, ContentType
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    ArtifactsCollectedCommand,
    CompletePhaseCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionStatus,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.artifact_recovery import (
    RECOVERED_SOURCE_PATH,
    recover_deliverable,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.command_report import (
    CommandsReport,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.command_gate import (
        RecordedCommands,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
        ArtifactCollector,
    )

logger = logging.getLogger(__name__)

__all__ = [
    "CollectedCommands",
    "SalvagedPhase",
    "collect_recorded_commands",
    "salvage_stranded_phase",
]

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
    recovered_from: str
    """How the deliverable was recovered, worded to finish "Phase 'x' ..."."""
    ended_the_run: bool = False
    """The collection itself ended the execution: a red command gate (ADR-078 D5)."""


@dataclass(frozen=True)
class CollectedCommands:
    """The `commands.json` that `collect_recorded_commands` stored."""

    artifact_id: str
    source_path: str
    content: str


async def collect_recorded_commands(
    aggregate: WorkflowExecutionAggregate,
    *,
    collector: ArtifactCollector,
    phase_id: str,
    phase_name: str,
    session_id: str | None,
    recorded: RecordedCommands,
    agent: AgentIdentity,
) -> CollectedCommands:
    """Store `commands.json` rebuilt from the event, tails lost, and collect the phase (D6).

    The one way a command Phase is collected without its workspace, in process
    or after a restart. The aggregate then rules on the verdict (D5) and is
    left holding the events, NOT persisted.
    """
    execution_id = aggregate.aggregate_id or ""
    report = CommandsReport.from_record(
        phase_id, success=recorded.success, timed_out=recorded.timed_out, steps=recorded.steps
    )
    ((path, body),) = report.files()
    content = body.decode()
    artifact_id = str(uuid4())
    await collector.create_artifact(
        artifact_id=artifact_id,
        workflow_id=aggregate.workflow_id or "",
        phase_id=phase_id,
        execution_id=execution_id,
        session_id=session_id or "",
        artifact_type="json",
        content=content,
        title=f"{phase_name}: {path}",
        agent=agent,
        source_path=path,
        content_type=ContentType.APPLICATION_JSON,
    )
    aggregate.artifacts_collected(
        ArtifactsCollectedCommand(
            execution_id=execution_id,
            phase_id=phase_id,
            artifact_ids=[artifact_id],
            first_content_preview=content[:500],
            session_id=session_id,
        )
    )
    return CollectedCommands(artifact_id=artifact_id, source_path=path, content=content)


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

    A command Phase's salvage may END the execution: a red gate fails it as
    `gate` (ADR-078 D5), and `ended_the_run` says so.
    """
    phase_id = aggregate.running_phase_id
    if aggregate.status is ExecutionStatus.RUNNING and phase_id is not None:
        commands = aggregate.recorded_commands_for(phase_id)
        if commands is not None:
            return await _salvage_commands(aggregate, phase_id, commands, collector=collector)
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

    artifact_id = str(uuid4())
    await collector.create_artifact(
        artifact_id=artifact_id,
        workflow_id=stranded.workflow_id,
        phase_id=stranded.phase_id,
        execution_id=stranded.execution_id,
        session_id=stranded.session_id,
        artifact_type=_RECOVERED_ARTIFACT_TYPE,
        content=recovered.content,
        title=recovered.title,
        source_path=recovered.source_path,
        # Nobody looked, and that is the honest record (#1284). This runs
        # after a restart, so the process holds none of the phase's runtime
        # state: the stream that was the only thing to ever name the model is
        # gone, and the provider lived beside it. Naming the CONFIGURED model
        # here would be the exact failure `AgentIdentity` exists to prevent -
        # the requested model wearing the name of the one that ran, which
        # reads as proof of a cross-model check and is not any.
        agent=AgentIdentity(provider=None, model=None),
    )

    aggregate.artifacts_collected(
        ArtifactsCollectedCommand(
            execution_id=stranded.execution_id,
            phase_id=stranded.phase_id,
            artifact_ids=[artifact_id],
            first_content_preview=recovered.content,
            session_id=stranded.session_id,
            deliverable_recovered=True,
        )
    )
    _complete_salvaged(
        aggregate,
        stranded.execution_id,
        stranded.workflow_id,
        stranded.phase_id,
        session_id=stranded.session_id,
        artifact_id=artifact_id,
    )
    logger.warning(
        "Recovered the deliverable of phase %s (%s) in execution %s from its "
        "transcript: a restart interrupted its collection, and without this "
        "the finished work would have been discarded with the execution (#1300)",
        stranded.phase_id,
        stranded.phase_name,
        stranded.execution_id,
    )
    return SalvagedPhase(
        phase_id=stranded.phase_id,
        phase_name=stranded.phase_name,
        artifact_id=artifact_id,
        recovered_from=(
            "had already finished its agent run, so its deliverable was recovered "
            "from the transcript"
        ),
    )


async def _salvage_commands(
    aggregate: WorkflowExecutionAggregate,
    phase_id: str,
    commands: RecordedCommands,
    *,
    collector: ArtifactCollector,
) -> SalvagedPhase:
    """Collect a command Phase from its recorded verdict; complete it if the gate passed."""
    collected = await collect_recorded_commands(
        aggregate,
        collector=collector,
        phase_id=phase_id,
        phase_name=commands.phase_name,
        session_id=None,
        recorded=commands,
        # Nobody ran an agent, and nobody is left to say who ran the steps.
        agent=AgentIdentity(provider=None, model=None),
    )
    execution_id = aggregate.aggregate_id or ""
    if commands.success:
        _complete_salvaged(
            aggregate,
            execution_id,
            aggregate.workflow_id or "",
            phase_id,
            session_id=None,
            artifact_id=collected.artifact_id,
        )
    logger.warning(
        "Collected the recorded verdict of command phase %s (%s) in execution %s "
        "after a restart; its step output was lost with the workspace (#2169)",
        phase_id,
        commands.phase_name,
        execution_id,
    )
    return SalvagedPhase(
        phase_id=phase_id,
        phase_name=commands.phase_name,
        artifact_id=collected.artifact_id,
        recovered_from=(
            "had already recorded its command steps' verdict, so commands.json was "
            "rebuilt from the event stream with its step output lost"
        ),
        ended_the_run=aggregate.status is not ExecutionStatus.RUNNING,
    )


def _complete_salvaged(
    aggregate: WorkflowExecutionAggregate,
    execution_id: str,
    workflow_id: str,
    phase_id: str,
    *,
    session_id: str | None,
    artifact_id: str,
) -> None:
    """Complete a salvaged phase, as the live path would, with no measurements."""
    aggregate.complete_phase(
        CompletePhaseCommand(
            execution_id=execution_id,
            workflow_id=workflow_id,
            phase_id=phase_id,
            session_id=session_id,
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
