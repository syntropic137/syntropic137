"""GlobalClaudePluginRegistry aggregate root (issue #726).

Singleton stream `global-claude-plugins` holding the list of globally-active
claude plugin references. Lookup detail (resolved_sha, tree prefix) lives on
the per-(source_url, version) ClaudePluginRegistrationAggregate; this aggregate
only owns the membership list.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from event_sourcing import AggregateRoot, aggregate, command_handler, event_sourcing_handler

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.commands.AddGlobalClaudePluginCommand import (
        AddGlobalClaudePluginCommand,
    )
    from syn_domain.contexts.orchestration.domain.commands.RemoveGlobalClaudePluginCommand import (
        RemoveGlobalClaudePluginCommand,
    )
    from syn_domain.contexts.orchestration.domain.events.GlobalClaudePluginAddedEvent import (
        GlobalClaudePluginAddedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.GlobalClaudePluginRemovedEvent import (
        GlobalClaudePluginRemovedEvent,
    )


GLOBAL_CLAUDE_PLUGIN_REGISTRY_STREAM_ID = "global-claude-plugins"


@dataclass(frozen=True)
class GlobalClaudePluginEntry:
    name: str
    source_url: str
    version: str
    resolved_sha: str
    added_at: datetime


@aggregate("GlobalClaudePluginRegistry")
class GlobalClaudePluginRegistryAggregate(AggregateRoot["GlobalClaudePluginAddedEvent"]):
    _aggregate_type: str

    # Module-level constant duplicated for ergonomic access via the aggregate class
    STREAM_ID = GLOBAL_CLAUDE_PLUGIN_REGISTRY_STREAM_ID

    def __init__(self) -> None:
        super().__init__()
        self._plugins: list[GlobalClaudePluginEntry] = []

    def get_aggregate_type(self) -> str:
        return self._aggregate_type

    @property
    def plugins(self) -> list[GlobalClaudePluginEntry]:
        return list(self._plugins)

    def has(self, name: str) -> bool:
        return any(entry.name == name for entry in self._plugins)

    @command_handler("AddGlobalClaudePluginCommand")
    def add(self, command: AddGlobalClaudePluginCommand) -> None:
        from syn_domain.contexts.orchestration.domain.events.GlobalClaudePluginAddedEvent import (
            GlobalClaudePluginAddedEvent,
        )

        if self.id is None:
            self._initialize(command.aggregate_id)

        # Idempotency by name; the slice handler catches and short-circuits
        if self.has(command.name):
            msg = f"global claude plugin already added: {command.name}"
            raise ValueError(msg)

        event = GlobalClaudePluginAddedEvent(
            name=command.name,
            source_url=command.source_url,
            version=command.version,
            resolved_sha=command.resolved_sha,
            added_at=datetime.now(UTC),
        )
        self._apply(event)

    @command_handler("RemoveGlobalClaudePluginCommand")
    def remove(self, command: RemoveGlobalClaudePluginCommand) -> None:
        from syn_domain.contexts.orchestration.domain.events.GlobalClaudePluginRemovedEvent import (
            GlobalClaudePluginRemovedEvent,
        )

        if self.id is None or not self.has(command.name):
            msg = f"global claude plugin not present: {command.name}"
            raise ValueError(msg)

        event = GlobalClaudePluginRemovedEvent(
            name=command.name,
            removed_at=datetime.now(UTC),
        )
        self._apply(event)

    @event_sourcing_handler("GlobalClaudePluginAdded")
    def on_global_claude_plugin_added(self, event: GlobalClaudePluginAddedEvent) -> None:
        self._plugins = [
            *self._plugins,
            GlobalClaudePluginEntry(
                name=event.name,
                source_url=event.source_url,
                version=event.version,
                resolved_sha=event.resolved_sha,
                added_at=event.added_at,
            ),
        ]

    @event_sourcing_handler("GlobalClaudePluginRemoved")
    def on_global_claude_plugin_removed(self, event: GlobalClaudePluginRemovedEvent) -> None:
        self._plugins = [entry for entry in self._plugins if entry.name != event.name]
