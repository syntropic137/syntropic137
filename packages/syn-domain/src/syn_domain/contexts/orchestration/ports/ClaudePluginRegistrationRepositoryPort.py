"""Port interface for ClaudePluginRegistrationAggregate repository (issue #726).

Concurrent registers of the same (source_url, version) deterministically map
to the same stream id, so save_new() with ExpectedVersion.NoStream is the
first-writer-wins primitive used by the registration slice handler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_claude_plugin_registration.ClaudePluginRegistrationAggregate import (
        ClaudePluginRegistrationAggregate,
    )


class ClaudePluginRegistrationRepositoryPort(Protocol):
    async def get_by_id(self, aggregate_id: str) -> ClaudePluginRegistrationAggregate | None: ...

    async def save(self, aggregate: ClaudePluginRegistrationAggregate) -> None: ...

    async def save_new(self, aggregate: ClaudePluginRegistrationAggregate) -> None: ...

    async def exists(self, aggregate_id: str) -> bool: ...
