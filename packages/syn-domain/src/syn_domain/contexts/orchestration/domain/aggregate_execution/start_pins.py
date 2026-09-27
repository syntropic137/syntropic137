"""What an execution fixes about itself when it starts, and where a fork came from.

A fork runs the rest of its parent's work (ADR-014 s7). "The rest of it" is
only the same work if it is run the way the parent would have run it, so the
parent has to have written that down when IT started - not left it to be looked
up in the workflow template later, which may have been edited in between (#1454)
and would then hand the fork a phase the parent never had. The same goes for
the code the parent ran against (#1457).

So `WorkflowExecutionStarted` carries three things beyond its phase list, all
defined here:

* the full runnable config of every phase (`pinned_phases`) - provider, model
  as resolved at start, prompt, sandbox, tools, plugins, skills;
* the commit each repository was at (`source_commits`);
* for a fork only, what it inherited and where it resumes (`forked_from`).

The readers below are the replay seam for them. They accept both what a typed
event holds and the plain data an ADR-023 `GenericDomainEvent` hands back.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from syn_domain.contexts.orchestration.domain.aggregate_execution.replay import evt
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,
    ForkOrigin,
    InheritedPhase,
    PhaseDefinition,
    SourceCommit,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from event_sourcing import DomainEvent

logger = logging.getLogger(__name__)


# Re-exported: `SourceCommit` and `ForkOrigin` now live in `value_objects`,
# because the start EVENT carries them and a domain event may not import from an
# aggregate's internals (vsa). Kept importable from here so the many modules that
# read them alongside the other pins do not all have to move.
__all__ = [
    "AdmittedFork",
    "ForkOrigin",
    "SourceCommit",
    "StartPins",
]


class StartPins(BaseModel):
    """Everything an execution pinned about itself at start, as replayed.

    The aggregate holds one of these rather than four loose fields, so what a
    fork of it inherits is read from a single place (#1454, #1457).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    inputs: dict[str, str] = Field(default_factory=dict)
    pinned_phases: list[ExecutablePhase] = Field(default_factory=list)
    source_commits: list[SourceCommit] = Field(default_factory=list)
    #: Set on a fork only: the parent this run was forked from.
    forked_from: ForkOrigin | None = None


class AdmittedFork(BaseModel):
    """The fork a parent admitted, as its `ExecutionForked` fixed it.

    Read back to build the child's start, never recomputed: the parent's state
    may have moved on since, and the decision is the one that was recorded.
    `fork_execution_id` can replay as None under ADR-023; a start built from
    that is refused, never invented (`fork_start.fork_start_command`).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    fork_execution_id: str | None = None
    inherited_phases: list[InheritedPhase] = Field(default_factory=list)
    resume_phase_id: str | None = None


def phase_definitions_of(phases: Sequence[ExecutablePhase]) -> list[PhaseDefinition]:
    """The sequencing view of a runnable phase list.

    One spelling for the fresh start and the fork, so the phase timeout the
    aggregate sequences by is derived the same way on both.
    """
    return [
        PhaseDefinition(
            phase_id=p.phase_id,
            name=p.name,
            order=p.order,
            timeout_seconds=p.timeout_seconds or p.agent_config.timeout_seconds,
        )
        for p in phases
    ]


_PINNED_PHASES: TypeAdapter[list[ExecutablePhase]] = TypeAdapter(list[ExecutablePhase])
_SOURCE_COMMITS: TypeAdapter[list[SourceCommit]] = TypeAdapter(list[SourceCommit])
_INHERITED_PHASES: TypeAdapter[list[InheritedPhase]] = TypeAdapter(list[InheritedPhase])


def read_inputs(raw: object) -> dict[str, str]:
    """What the execution was asked to do, as a fork will be asked it again.

    `str` values because that is what reaches the start event: the only way in
    is `ExecuteWorkflowCommand.inputs`, a `dict[str, str]`, and what the
    processor adds (`repos`) is a string too. The coercion is for a payload
    written some other way, and is lossless for everything written this way.
    """
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def read_pinned_phases(raw: object) -> list[ExecutablePhase]:
    """The pinned phases, or empty when absent or unreadable.

    Empty is safe to fall back to because it fails CLOSED: a parent with no
    pinned phases cannot be forked (`fork_rules.refuse_fork_start`), so a
    snapshot this reader cannot trust is never run from.
    """
    if not raw:
        return []
    try:
        return _PINNED_PHASES.validate_python(raw)
    except ValidationError:
        logger.warning("Unreadable pinned_phases on a replayed start event; treating as absent")
        return []


def read_source_commits(raw: object) -> list[SourceCommit]:
    """The recorded source commits, or empty when absent or unreadable."""
    if not raw:
        return []
    try:
        return _SOURCE_COMMITS.validate_python(raw)
    except ValidationError:
        logger.warning("Unreadable source_commits on a replayed start event; treating as absent")
        return []


def read_inherited_phases(raw: object) -> list[InheritedPhase]:
    """The inherited prefix on a replayed `ExecutionForked`."""
    return _INHERITED_PHASES.validate_python(raw or [])


def read_start_pins(event: DomainEvent) -> StartPins:
    """The pins on a replayed `WorkflowExecutionStarted`, typed or generic."""
    return StartPins(
        inputs=read_inputs(evt(event, "inputs")),
        pinned_phases=read_pinned_phases(evt(event, "pinned_phases")),
        source_commits=read_source_commits(evt(event, "source_commits")),
        forked_from=read_fork_origin(evt(event, "forked_from")),
    )


def read_admitted_fork(event: DomainEvent) -> AdmittedFork:
    """The fork a replayed `ExecutionForked` admitted, typed or generic."""
    return AdmittedFork(
        fork_execution_id=evt(event, "fork_execution_id"),
        inherited_phases=read_inherited_phases(evt(event, "inherited_phases")),
        resume_phase_id=evt(event, "resume_phase_id"),
    )


def read_fork_origin(raw: object) -> ForkOrigin | None:
    """Where this execution was forked from, or None for one that was not.

    Deliberately NOT forgiving, unlike the two readers above. Absent means "not
    a fork"; present-but-unreadable raises, because treating it as absent would
    replay a fork as a fresh run - one whose inherited phases are no longer
    closed, which is the fail-open this whole feature exists to prevent.
    """
    if raw is None:
        return None
    return ForkOrigin.model_validate(raw)
