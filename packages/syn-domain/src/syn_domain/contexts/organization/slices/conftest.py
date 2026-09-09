"""Shared test fixtures for organization insight handler tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime

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


class FakeProjectionStore:
    """In-memory projection store for testing, which remembers what it was asked.

    `asks` records every `query`, `scans` every `get_all`. Together they let a
    test assert that a read was pushed DOWN rather than done in Python, without
    a bespoke spy subclass per test - which is what this replaced, and which
    had to restate the whole store signature to record one field.
    """

    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict[str, Any]]] = {}
        self._positions: dict[str, int] = {}
        self.asks: list[Ask] = []
        self.scans: list[str] = []

    async def save(self, projection: str, key: str, data: dict[str, Any]) -> None:
        self._data.setdefault(projection, {})[key] = data

    async def get(self, projection: str, key: str) -> dict[str, Any] | None:
        return self._data.get(projection, {}).get(key)

    async def get_all(self, projection: str) -> list[dict[str, Any]]:
        self.scans.append(projection)
        return list(self._data.get(projection, {}).values())

    async def delete(self, projection: str, key: str) -> None:
        self._data.get(projection, {}).pop(key, None)

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
        records = list(self._data.get(projection, {}).values())
        if filters:
            records = [
                r for r in records if all(r.get(k) in _wanted(v) for k, v in filters.items())
            ]
        if order_by:
            reverse = order_by.startswith("-")
            field = order_by.lstrip("-")
            records.sort(key=lambda r: (r.get(field) is None, r.get(field)), reverse=reverse)
        if offset:
            records = records[offset:]
        if limit is not None:
            records = records[:limit]
        return records

    async def get_position(self, projection: str) -> int | None:
        return self._positions.get(projection)

    async def set_position(self, projection: str, position: int) -> None:
        self._positions[projection] = position

    async def get_by_prefix(self, projection: str, prefix: str) -> list[tuple[str, dict[str, Any]]]:
        if projection not in self._data:
            return []
        return [
            (key, data) for key, data in self._data[projection].items() if key.startswith(prefix)
        ][:10]

    async def delete_all(self, projection: str) -> None:
        self._data.pop(projection, None)

    async def get_last_updated(self, projection: str) -> datetime | None:  # noqa: ARG002
        return None


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
