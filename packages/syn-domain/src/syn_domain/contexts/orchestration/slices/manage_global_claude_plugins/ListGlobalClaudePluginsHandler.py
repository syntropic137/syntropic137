"""ListGlobalClaudePlugins query handler (issue #726)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.slices.manage_global_claude_plugins.projection import (
        GlobalClaudePluginEntry,
        GlobalClaudePluginsProjection,
    )


class ListGlobalClaudePluginsHandler:
    def __init__(self, projection: GlobalClaudePluginsProjection) -> None:
        self._projection = projection

    async def handle(self) -> list[GlobalClaudePluginEntry]:
        entries = await self._projection.list_all()
        return sorted(entries, key=lambda e: e.name)
