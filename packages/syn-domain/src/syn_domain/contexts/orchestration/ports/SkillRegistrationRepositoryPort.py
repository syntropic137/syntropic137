"""Port interface for SkillRegistrationAggregate repository (issue #772).

Concurrent registers of the same (source_url, version, skill_name)
deterministically map to the same stream id, so save_new() with
ExpectedVersion.NoStream is the first-writer-wins primitive used by the
registration slice handler. Mirrors ClaudePluginRegistrationRepositoryPort
(issue #726).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_skill_registration.SkillRegistrationAggregate import (
        SkillRegistrationAggregate,
    )


class SkillRegistrationRepositoryPort(Protocol):
    # The identifier below is positional-only. The implementation is the generic
    # RepositoryAdapter[TAggregate], which necessarily names it aggregate_id, and
    # Protocol matching compares parameter NAMES for anything not positional-only
    # -- so a domain-specific name here would leave this port unsatisfiable (#1305).
    async def get_by_id(self, aggregate_id: str, /) -> SkillRegistrationAggregate | None: ...

    async def save(self, aggregate: SkillRegistrationAggregate) -> None: ...

    async def save_new(self, aggregate: SkillRegistrationAggregate) -> None: ...

    async def exists(self, aggregate_id: str, /) -> bool: ...
