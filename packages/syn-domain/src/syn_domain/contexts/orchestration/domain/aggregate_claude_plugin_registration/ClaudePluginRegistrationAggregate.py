"""ClaudePluginRegistration aggregate root (issue #726).

One aggregate per (source_url, version, name). Identity is deterministic:
`claude-plugin-{sha256(source_url|version|name)}`. The `name` component is
load-bearing for marketplace repos: a single (source_url, version) can host
many plugins (e.g. AgentParadise/agentic-primitives@main exposes sdlc,
workspace, observability, ...). Hashing on the lookup key without `name`
collapses them all to the same stream id and the first registration shadows
the rest. The fix lands as a non-deployed schema change (no live state to
migrate); existing dev-only entries become orphans and the user re-registers
via `--force`.

The slice handler that calls register() uses repository.save_new() with
ExpectedVersion.NoStream so two concurrent registrations of the same
reference collide cleanly; the losing writer reads the existing aggregate
and short-circuits.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from event_sourcing import AggregateRoot, aggregate, command_handler, event_sourcing_handler

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.commands.RegisterClaudePluginCommand import (
        RegisterClaudePluginCommand,
    )
    from syn_domain.contexts.orchestration.domain.events.ClaudePluginRegisteredEvent import (
        ClaudePluginRegisteredEvent,
    )


def compute_claude_plugin_stream_id(source_url: str, version: str, name: str) -> str:
    """Deterministic stream id derived from the lookup key.

    Why a single hashed id instead of three indexed columns: avoids needing
    a secondary index just to enforce uniqueness on the lookup key - the
    event store's per-stream NoStream check does it for us.

    Why `name` is part of the key: marketplace repos (agentic-primitives,
    obra/superpowers, ...) ship multiple plugins at the same
    (source_url, version). Hashing without `name` collapses them all to one
    stream and only the first plugin registered survives.
    """
    digest = hashlib.sha256(f"{source_url}|{version}|{name}".encode()).hexdigest()
    return f"claude-plugin-{digest}"


@aggregate("ClaudePluginRegistration")
class ClaudePluginRegistrationAggregate(AggregateRoot["ClaudePluginRegisteredEvent"]):
    _aggregate_type: str

    def __init__(self) -> None:
        super().__init__()
        self._source_url: str | None = None
        # Avoid clashing with BaseAggregate.version (event-store stream version, int)
        self._plugin_version: str | None = None
        self._resolved_sha: str | None = None
        self._name: str | None = None
        self._tree_storage_prefix: str | None = None
        # WHY ``dict[str, object]`` (issue #726): plugin.json may contain
        # arrays and nested objects; manifest is opaque metadata downstream.
        self._manifest: dict[str, object] = {}
        self._registered_at: datetime | None = None

    def get_aggregate_type(self) -> str:
        return self._aggregate_type

    @staticmethod
    def compute_stream_id(source_url: str, version: str, name: str) -> str:
        return compute_claude_plugin_stream_id(source_url, version, name)

    @property
    def source_url(self) -> str | None:
        return self._source_url

    @property
    def plugin_version(self) -> str | None:
        return self._plugin_version

    @property
    def resolved_sha(self) -> str | None:
        return self._resolved_sha

    @property
    def name(self) -> str | None:
        return self._name

    @property
    def tree_storage_prefix(self) -> str | None:
        return self._tree_storage_prefix

    @property
    def manifest(self) -> dict[str, object]:
        return dict(self._manifest)

    @property
    def registered_at(self) -> datetime | None:
        return self._registered_at

    @command_handler("RegisterClaudePluginCommand")
    def register(self, command: RegisterClaudePluginCommand) -> None:
        from syn_domain.contexts.orchestration.domain.events.ClaudePluginRegisteredEvent import (
            ClaudePluginRegisteredEvent,
        )

        if self.id is not None:
            msg = "Claude plugin already registered"
            raise ValueError(msg)

        self._initialize(command.aggregate_id)

        event = ClaudePluginRegisteredEvent(
            source_url=command.source_url,
            version=command.version,
            resolved_sha=command.resolved_sha,
            name=command.name,
            tree_storage_prefix=command.tree_storage_prefix,
            manifest=dict(command.manifest),
            registered_at=datetime.now(UTC),
        )
        self._apply(event)

    @event_sourcing_handler("ClaudePluginRegistered")
    def on_claude_plugin_registered(self, event: ClaudePluginRegisteredEvent) -> None:
        self._source_url = event.source_url
        self._plugin_version = event.version
        self._resolved_sha = event.resolved_sha
        self._name = event.name
        self._tree_storage_prefix = event.tree_storage_prefix
        self._manifest = dict(event.manifest)
        self._registered_at = event.registered_at
