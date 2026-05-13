"""ListClaudePlugins query handler (issue #726).

Returns every entry in the lock projection (every (source_url, version) ever
registered, regardless of whether any global / workflow / phase scope still
references it). Sorted by ``(name, version)`` for stable CLI output.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.slices.register_claude_plugin.projection import (
        ClaudePluginLockProjection,
        LockEntry,
    )


class ListClaudePluginsHandler:
    def __init__(self, projection: ClaudePluginLockProjection) -> None:
        self._projection = projection

    async def handle(self) -> list[LockEntry]:
        entries = await self._projection.list_all()
        return sorted(entries, key=lambda e: (e.name, e.version))
