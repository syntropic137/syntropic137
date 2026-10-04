"""What each phase of an execution was configured with when it started (#1454).

The answer is read from the execution's own `WorkflowExecutionStarted` event,
by loading the aggregate that replays it, rather than from the detail
projection. The projection never stored the pins, and teaching it to would have
needed a VERSION bump - a full replay of every execution - before any existing
run could show them. The start event already holds them, so reading it costs
one stream load per detail request and nothing at deploy time.

Two different absences, kept apart: a read stream whose start event carries no
pins for a phase is "not recorded" (the execution predates #1454); a stream
that could not be read is "unavailable" and says nothing about what was
recorded. Neither is ever filled in from the workflow template, which may have
been edited since the run started.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from syn_api.types import PhaseStartConfig, PinnedSkillInfo

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ExecutablePhase,
    )

logger = logging.getLogger(__name__)


def _start_config(phase: ExecutablePhase) -> PhaseStartConfig:
    return PhaseStartConfig(
        provider=str(phase.agent_config.provider),
        requested_model=phase.agent_config.model,
        allowed_tools=list(phase.agent_config.allowed_tools),
        skills=[
            PinnedSkillInfo(
                name=s.skill_name,
                version=s.version,
                resolved_sha=s.resolved_sha,
                source_url=s.source_url,
            )
            for s in phase.skills
        ],
    )


async def load_start_configs(execution_id: str) -> dict[str, PhaseStartConfig] | None:
    """Each phase's pinned start config, by phase id. Missing key = not recorded.

    ``None`` = unavailable: the stream could not be read, so whether anything
    was recorded is unknown. Fails soft - the pins are context for a reader,
    and an unreadable stream must not fail the detail read it decorates - but
    never as ``{}``, which would claim the start event was read and was empty.
    """
    from syn_api._wiring import get_workflow_execution_repository

    try:
        aggregate = await get_workflow_execution_repository().get_by_id(execution_id)
    except Exception:
        logger.exception("Could not load execution %s to read its start pins", execution_id)
        return None
    if aggregate is None:
        # The detail projection has this execution, so its stream exists; not
        # finding it here is a failed read, not an answer.
        logger.warning("Execution %s has no stream to read its start pins from", execution_id)
        return None
    return {p.phase_id: _start_config(p) for p in aggregate.start_pins.pinned_phases}
