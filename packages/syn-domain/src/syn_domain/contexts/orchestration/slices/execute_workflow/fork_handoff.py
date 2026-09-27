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
    from syn_domain.contexts.artifacts import PhaseOutputFile
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

    Read by artifact id from the execution that RAN each inherited phase,
    because that is where its artifacts were stored (#1462). For a first fork
    that is the parent; for a fork of a fork, a phase the parent itself
    inherited is owned further up, and asking the parent finds nothing. The
    head of each phase's files is its alias, as it is for a phase run live.

    Raises `InheritanceUnavailableError` rather than returning a short cache.
    Two ways that used to pass silently, both of which start a child whose
    resumed phase cannot see what it is resuming from:

    * no query service at all, while the origin names phases to inherit;
    * a query that SUCCEEDS and returns nothing for a phase whose owner
      recorded artifact ids - a deleted, expired or unreachable artifact.

    An inherited phase that recorded NO artifact ids is not one of those cases:
    it produced nothing, so nothing is missing, and it is passed over.
    """
    cache = PhaseOutputCache()
    if origin is None or not origin.inherited_phases:
        return cache

    expected = sorted(p.phase_id for p in origin.inherited_phases if p.artifact_ids)
    if query is None:
        if expected:
            msg = (
                f"Cannot hand fork of {origin.parent_execution_id} its inheritance: "
                f"phase(s) {expected} recorded artifacts and no artifact "
                "query service was wired to read them"
            )
            raise InheritanceUnavailableError(msg)
        return cache

    wanted_by_owner: dict[str, dict[str, list[str]]] = {}
    for phase in origin.inherited_phases:
        wanted_by_owner.setdefault(origin.owner_of(phase), {})[phase.phase_id] = list(
            phase.artifact_ids
        )
    files: dict[str, list[PhaseOutputFile]] = {}
    for owner, wanted in wanted_by_owner.items():
        found = await query.get_files_for_artifacts(owner, wanted)
        unresolved = sorted(p for p, ids in wanted.items() if ids and not found.get(p))
        if unresolved:
            msg = (
                f"Cannot hand fork of {origin.parent_execution_id} its inheritance: "
                f"execution {owner}, which ran phase(s) {unresolved}, holds no files "
                "for the artifact ids they recorded"
            )
            raise InheritanceUnavailableError(msg)
        files.update(found)

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
