"""In-memory repositories for skill aggregates - TESTS ONLY (issue #772).

Used by register_skill slice tests so they do not need a real event store.
Mirrors the ``RepositoryAdapter`` shape used by production wiring
(``get_by_id``, ``save``, ``save_new``, ``exists``). Mirrors
``in_memory_claude_plugin_repositories.py`` (issue #726).

``save_new`` raises the SDK's ``StreamAlreadyExistsError`` to mirror
production semantics so handler dedup paths exercise the real code path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from event_sourcing import StreamAlreadyExistsError

from syn_adapters.in_memory import InMemoryAdapter

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_skill_registration.SkillRegistrationAggregate import (
        SkillRegistrationAggregate,
    )


class InMemorySkillRegistrationRepository(InMemoryAdapter):
    """In-memory ``SkillRegistrationAggregate`` repository for tests."""

    def __init__(self) -> None:
        super().__init__()
        self._store: dict[str, SkillRegistrationAggregate] = {}

    async def get_by_id(self, aggregate_id: str) -> SkillRegistrationAggregate | None:
        return self._store.get(aggregate_id)

    async def save(self, aggregate: SkillRegistrationAggregate) -> None:
        if aggregate.id is None:
            msg = "Aggregate id is None - aggregate has no events applied"
            raise ValueError(msg)
        self._store[str(aggregate.id)] = aggregate

    async def save_new(self, aggregate: SkillRegistrationAggregate) -> None:
        if aggregate.id is None:
            msg = "Aggregate id is None - cannot save_new without identity"
            raise ValueError(msg)
        if str(aggregate.id) in self._store:
            # Mirror real event store: NoStream conflict on existing stream.
            raise StreamAlreadyExistsError(str(aggregate.id), 0)
        self._store[str(aggregate.id)] = aggregate

    async def exists(self, aggregate_id: str) -> bool:
        return aggregate_id in self._store
