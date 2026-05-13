"""Port interface for GlobalClaudePluginRegistryAggregate repository (issue #726).

Singleton aggregate keyed by `global-claude-plugins`. save_new() exists for
the first-time bootstrap; everyday add/remove use save().
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_global_claude_plugin_registry.GlobalClaudePluginRegistryAggregate import (
        GlobalClaudePluginRegistryAggregate,
    )


class GlobalClaudePluginRegistryRepositoryPort(Protocol):
    async def get_by_id(self, aggregate_id: str) -> GlobalClaudePluginRegistryAggregate | None: ...

    async def save(self, aggregate: GlobalClaudePluginRegistryAggregate) -> None: ...

    async def save_new(self, aggregate: GlobalClaudePluginRegistryAggregate) -> None: ...

    async def exists(self, aggregate_id: str) -> bool: ...
