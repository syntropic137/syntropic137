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
    # The identifier below is positional-only. The implementation is the generic
    # RepositoryAdapter[TAggregate], which necessarily names it aggregate_id, and
    # Protocol matching compares parameter NAMES for anything not positional-only
    # -- so a domain-specific name here would leave this port unsatisfiable (#1305).
    async def get_by_id(self, aggregate_id: str, /) -> GlobalClaudePluginRegistryAggregate | None: ...

    async def save(self, aggregate: GlobalClaudePluginRegistryAggregate) -> None: ...

    async def save_new(self, aggregate: GlobalClaudePluginRegistryAggregate) -> None: ...

    async def exists(self, aggregate_id: str, /) -> bool: ...
