"""RemoveGlobalClaudePlugin command handler (issue #726).

Removes a plugin from the singleton global registry by display name. The
underlying ``ClaudePluginRegistrationAggregate`` (lock entry) is left in
place so any workflow that pinned that exact (source_url, version) still
resolves cleanly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.aggregate_global_claude_plugin_registry.GlobalClaudePluginRegistryAggregate import (
    GLOBAL_CLAUDE_PLUGIN_REGISTRY_STREAM_ID,
)
from syn_domain.contexts.orchestration.domain.commands.RemoveGlobalClaudePluginCommand import (
    RemoveGlobalClaudePluginCommand,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.ports.GlobalClaudePluginRegistryRepositoryPort import (
        GlobalClaudePluginRegistryRepositoryPort,
    )


@dataclass(frozen=True)
class RemoveGlobalClaudePluginResult:
    """Returned to confirm the removal."""

    name: str


class GlobalClaudePluginNotFoundError(Exception):
    """Raised when a remove targets a plugin that is not in the global registry."""

    def __init__(self, name: str) -> None:
        super().__init__(f"Global claude plugin not found: {name}")
        self.name = name


class RemoveGlobalClaudePluginHandler:
    def __init__(self, repo: GlobalClaudePluginRegistryRepositoryPort) -> None:
        self._repo = repo

    async def handle(self, name: str) -> RemoveGlobalClaudePluginResult:
        aggregate = await self._repo.get_by_id(GLOBAL_CLAUDE_PLUGIN_REGISTRY_STREAM_ID)
        if aggregate is None or not aggregate.has(name):
            # Translate domain ValueError into a clearer typed error so the API
            # layer can map it cleanly without string sniffing.
            raise GlobalClaudePluginNotFoundError(name)

        command = RemoveGlobalClaudePluginCommand(
            aggregate_id=GLOBAL_CLAUDE_PLUGIN_REGISTRY_STREAM_ID,
            name=name,
        )
        aggregate.remove(command)
        await self._repo.save(aggregate)
        return RemoveGlobalClaudePluginResult(name=name)
