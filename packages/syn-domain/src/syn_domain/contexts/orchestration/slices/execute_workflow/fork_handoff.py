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


class InheritanceUnavailableError(RuntimeError):
    """A fork's inherited outputs could not be handed to its resumed phase.

    Raised BEFORE the child's stream opens, which is why it is an error and not
    a degraded cache: the resumed phase reads its predecessors' files, and a
    child that starts without them runs the wrong work at full price and reports
    success. Refusing to start is recoverable; a silently wrong resume is not.
    """


async def inherited_outputs(
    query: ArtifactQueryServiceProtocol | None,
    origin: ForkOrigin | None,
) -> PhaseOutputCache:
    """The output cache a run starts with: empty, or a fork's inheritance.

    Read by artifact id from the PARENT's execution, because that is where the
    artifacts were stored and the child's own id finds none of them. The head
    of each phase's files is its alias, as it is for a phase run live.

    Raises `InheritanceUnavailableError` rather than returning a short cache.
    Two ways that used to pass silently, both of which start a child whose
    resumed phase cannot see what it is resuming from:

    * no query service at all, while the origin names phases to inherit;
    * a query that SUCCEEDS and returns nothing for a phase whose parent
      recorded artifact ids - a deleted, expired or unreachable artifact.

    An inherited phase that recorded NO artifact ids is not one of those cases:
    it produced nothing, so nothing is missing, and it is passed over.
    """
    cache = PhaseOutputCache()
    if origin is None or not origin.inherited_phases:
        return cache

    wanted = {p.phase_id: list(p.artifact_ids) for p in origin.inherited_phases}
    expected = {phase_id for phase_id, ids in wanted.items() if ids}
    if query is None:
        if expected:
            msg = (
                f"Cannot hand fork of {origin.parent_execution_id} its inheritance: "
                f"phase(s) {sorted(expected)} recorded artifacts and no artifact "
                "query service was wired to read them"
            )
            raise InheritanceUnavailableError(msg)
        return cache

    files = await query.get_files_for_artifacts(origin.parent_execution_id, wanted)
    unresolved = sorted(phase_id for phase_id in expected if not files.get(phase_id))
    if unresolved:
        msg = (
            f"Cannot hand fork of {origin.parent_execution_id} its inheritance: "
            f"phase(s) {unresolved} recorded artifacts that resolved to no files"
        )
        raise InheritanceUnavailableError(msg)

    # A phase can still resolve PARTIALLY - two artifact ids recorded, one of
    # them gone - and this function CANNOT see that. `get_files_for_artifacts`
    # returns files, `PhaseOutputFile` carries no artifact id, and one artifact is
    # a directory of many files, so file count cannot be compared with id count
    # in either direction. Detecting it needs the query to report which ids it
    # resolved; #1460 tracks that. Refusing on a count here would be a false
    # invariant, not a safer one.
    for phase_id, phase_files in files.items():
        cache.record(phase_id, phase_files[0].content if phase_files else None, phase_files)
    return cache


def inherited_phase_ids(origin: ForkOrigin | None) -> list[str]:
    """The phases a run begins with already complete, in phase order."""
    return [] if origin is None else [p.phase_id for p in origin.inherited_phases]
