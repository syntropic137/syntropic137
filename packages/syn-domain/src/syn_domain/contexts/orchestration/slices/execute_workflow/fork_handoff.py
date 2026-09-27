"""What a fork hands its resumed phase from the phases it inherited (ADR-014 s7).

A fork never runs its inherited phases, so nothing in its own run records what
they produced - and the phase it resumes at may read exactly that. The parent
named the artifacts each inherited phase kept; this turns those names into the
per-run output cache the processor fills for every phase it DOES run, so the
resumed phase is provisioned the way it would have been had the parent carried
on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    PhaseOutputCache,
)

if TYPE_CHECKING:
    from syn_domain.contexts.artifacts.domain.services.artifact_query_service import (
        ArtifactQueryServiceProtocol,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.start_pins import (
        ForkOrigin,
    )


async def inherited_outputs(
    query: ArtifactQueryServiceProtocol | None,
    origin: ForkOrigin | None,
) -> PhaseOutputCache:
    """The output cache a run starts with: empty, or a fork's inheritance.

    Read by artifact id from the PARENT's execution, because that is where the
    artifacts were stored and the child's own id finds none of them. The head
    of each phase's files is its alias, as it is for a phase run live.
    """
    cache = PhaseOutputCache()
    if origin is None or query is None or not origin.inherited_phases:
        return cache
    files = await query.get_files_for_artifacts(
        origin.parent_execution_id,
        {p.phase_id: p.artifact_ids for p in origin.inherited_phases},
    )
    for phase_id, phase_files in files.items():
        cache.record(phase_id, phase_files[0].content if phase_files else None, phase_files)
    return cache


def inherited_phase_ids(origin: ForkOrigin | None) -> list[str]:
    """The phases a run begins with already complete, in phase order."""
    return [] if origin is None else [p.phase_id for p in origin.inherited_phases]
