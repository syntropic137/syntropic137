"""Shared test fixtures for organization insight handler tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.organization.slices.list_repos.projection import (
    RepoProjection,
)
from syn_domain.contexts.organization.slices.list_systems.projection import (
    SystemProjection,
)


def _wanted(value: object) -> tuple[object, ...]:
    """One filter value, or several meaning ANY of them.

    Mirrors `_condition` in syn_adapters.projection_stores.postgres_query_builder,
    which renders a collection as `= ANY($n)`. A fake that compared the list
    itself would answer [] to a query the real store answers, and every handler
    test filtering by more than one repo would pass for the wrong reason.
    """
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(value)
    return (value,)


@dataclass(frozen=True)
class AskFilter:
    """One predicate of a read, normalised past the caller's choice of spelling.

    `values` is always a tuple, so a test states what it expects once and does
    not have to know whether the caller passed a bare string, a list or the set
    comprehension the system-scoped handlers build.
    """

    field: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class Ask:
    """One read the code under test performed, as the store saw it.

    Recorded because some properties are about the QUESTION, not the answer.
    "The whole correlation projection is never loaded to satisfy a filter" is
    the point of #1253, and both spellings return the same executions, so a
    test that only looked at the result would pass either way.
    """

    projection: str
    filters: tuple[AskFilter, ...] = ()


@dataclass
class FakeProjectionStore(InMemoryProjectionStore):
    """The in-memory projection store, which also remembers what it was asked.

    `asks` records every `query`, `scans` every `get_all`. Together they let a
    test assert that a read was pushed DOWN rather than done in Python, without
    a bespoke spy subclass per test - which is what this replaced, and which
    had to restate the whole store signature to record one field.

    Storage, filtering and copy-on-read are the real store's, so a handler
    that edits a record it read and forgets to `save` fails here as it would
    against Postgres (#2124).
    """

    asks: list[Ask] = field(default_factory=list[Ask])
    scans: list[str] = field(default_factory=list[str])

    async def get_all(self, projection: str) -> list[dict[str, Any]]:
        self.scans.append(projection)
        return await super().get_all(projection)

    async def query(
        self,
        projection: str,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        self.asks.append(
            Ask(
                projection,
                tuple(
                    AskFilter(k, tuple(str(x) for x in _wanted(v)))
                    for k, v in (filters or {}).items()
                ),
            )
        )
        return await super().query(projection, filters, order_by, limit, offset)


async def _make_projections(
    system_id: str,
    system_name: str,
    org_id: str,
    repo_full_names: list[str],
    store: FakeProjectionStore | None = None,
) -> tuple[SystemProjection, RepoProjection]:
    """Create test projections with a system and its repos."""
    from syn_domain.contexts.organization.domain.events.RepoAssignedToSystemEvent import (
        RepoAssignedToSystemEvent,
    )
    from syn_domain.contexts.organization.domain.events.RepoRegisteredEvent import (
        RepoRegisteredEvent,
    )
    from syn_domain.contexts.organization.domain.events.SystemCreatedEvent import (
        SystemCreatedEvent,
    )

    if store is None:
        store = FakeProjectionStore()

    sys_proj = SystemProjection(store=store)
    repo_proj = RepoProjection(store=store)

    await sys_proj.handle_system_created(
        SystemCreatedEvent(
            system_id=system_id,
            organization_id=org_id,
            name=system_name,
            description="",
            created_by="test",
        )
    )

    for i, name in enumerate(repo_full_names):
        repo_id = f"repo-{i}"
        owner = name.split("/")[0] if "/" in name else ""
        await repo_proj.handle_repo_registered(
            RepoRegisteredEvent(
                repo_id=repo_id,
                organization_id=org_id,
                provider="github",
                provider_repo_id="",
                full_name=name,
                owner=owner,
                default_branch="main",
                installation_id="",
                is_private=False,
                created_by="test",
            )
        )
        await repo_proj.handle_repo_assigned_to_system(
            RepoAssignedToSystemEvent(
                repo_id=repo_id,
                system_id=system_id,
            )
        )

    return sys_proj, repo_proj
