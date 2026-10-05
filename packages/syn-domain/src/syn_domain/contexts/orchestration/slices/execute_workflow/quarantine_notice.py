"""The quarantine refs a failure event carries, as data (#1547).

`describe_saved_work` already tells a human reading `error_message` where the
work went. This is the same fact for a machine: one `QuarantinedRef` per
repository whose work LANDED, joined to the PR its branch had open, so the PR
can be told without anyone parsing prose.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    QuarantinedRef,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
        ObservedBranches,
        QuarantinedWork,
    )


def quarantined_refs(
    records: Sequence[QuarantinedWork],
    observed: ObservedBranches | None,
    repositories: Sequence[str],
) -> tuple[QuarantinedRef, ...]:
    """Every record that names a ref someone can fetch, with its PR when known.

    A record whose push failed is left out: it is reported in the error as
    lost, and a ref that does not exist is nothing to point a reviewer at.
    ``repositories`` are the execution's ``owner/name`` pins, matched to the
    clone's directory name the record carries; a record that matches none
    keeps the directory name, which no forge call will resolve and which is
    therefore never commented on.
    """
    full_name = {r.rsplit("/", 1)[-1]: r for r in repositories}
    open_pr = {
        (o.repo, o.branch): o.pull_request
        for o in (observed.branches if observed is not None else ())
        if o.pull_request is not None
    }
    return tuple(
        QuarantinedRef(
            repository=full_name.get(record.repo, record.repo),
            branch=record.branch,
            ref=record.pushed_ref,
            commit=record.commit,
            commit_count=record.commit_count,
            pull_request=open_pr.get((record.repo, record.branch)),
        )
        for record in records
        if record.pushed_ref is not None
    )
