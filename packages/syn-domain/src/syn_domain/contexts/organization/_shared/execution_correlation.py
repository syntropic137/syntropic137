"""Which executions belong to which repos - asked of the store, not of memory.

WHY THIS EXISTS. Nine call sites needed the same answer and each wrote the
same two lines to get it::

    correlations = await store.get_all(REPO_CORRELATION)
    return {c["execution_id"] for c in correlations if c.get("repo_full_name") in repo_names}

That loads every correlation record ever written and discards almost all of
them in Python. The cost is the whole table on every insight request, on a
question the store can answer with a predicate; it was the second of the two
full scans behind the 8-15s contribution-heatmap endpoint (#1253).

Nine copies also meant nine slightly different answers: some tolerated a
record missing ``execution_id`` and some raised ``KeyError`` on it, some
matched one repo and some a set. Asking once, here, makes that one decision
in one place - which is the point of the module, not a side effect of it.
Callers say which repos they mean and get back the correlation; how it is
fetched, and what a malformed record does, stop being their business.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.organization._shared.projection_names import REPO_CORRELATION

if TYPE_CHECKING:
    from collections.abc import Collection

    from event_sourcing import ProjectionStore


async def executions_by_repo(store: ProjectionStore, repo_names: Collection[str]) -> dict[str, str]:
    """Map each execution correlated with ``repo_names`` to its repo's full name.

    Callers wanting only the ids read the keys: ``set(await executions_by_repo(...))``.

    An empty ``repo_names`` means "no repo matches", not "no filter": it
    returns ``{}`` without touching the store, because a filter that resolved
    to nothing must not silently widen to everything. Records missing either
    half of the correlation are skipped - a half-written record identifies no
    execution, and dropping it here is what keeps every caller from having to
    decide.
    """
    if not repo_names:
        return {}
    correlations = await store.query(REPO_CORRELATION, filters={"repo_full_name": list(repo_names)})
    return {
        c["execution_id"]: c["repo_full_name"]
        for c in correlations
        if c.get("execution_id") and c.get("repo_full_name")
    }
