"""Global claude plugins projection (issue #726).

A flat list of currently-active global claude plugins. Built from
``GlobalClaudePluginAddedEvent`` and ``GlobalClaudePluginRemovedEvent``.
The Phase 5 resolution service walks this list as the outermost scope when
deciding what to materialize for a given workflow phase.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from event_sourcing import AutoDispatchProjection


@dataclass(frozen=True)
class GlobalClaudePluginEntry:
    """One global plugin entry in the read model."""

    name: str
    source_url: str
    version: str
    resolved_sha: str
    added_at: datetime


class GlobalClaudePluginsProjection(AutoDispatchProjection):
    """Read model for the global claude plugin registry singleton."""

    PROJECTION_NAME = "global_claude_plugins"
    VERSION = 1

    def __init__(self, store: object) -> None:
        self._store = store

    def get_name(self) -> str:
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        return self.VERSION

    async def clear_all_data(self) -> None:
        if hasattr(self._store, "delete_all"):
            await self._store.delete_all(self.PROJECTION_NAME)  # type: ignore[attr-defined]

    async def on_global_claude_plugin_added(self, event_data: dict[str, Any]) -> None:
        name = event_data.get("name")
        if not isinstance(name, str) or not name:
            return
        entry = GlobalClaudePluginEntry(
            name=name,
            source_url=str(event_data.get("source_url", "")),
            version=str(event_data.get("version", "")),
            resolved_sha=str(event_data.get("resolved_sha", "")),
            added_at=_coerce_datetime(event_data.get("added_at")),
        )
        await self._store.save(self.PROJECTION_NAME, name, _entry_to_dict(entry))  # type: ignore[attr-defined]

    async def on_global_claude_plugin_removed(self, event_data: dict[str, Any]) -> None:
        name = event_data.get("name")
        if not isinstance(name, str) or not name:
            return
        await self._store.delete(self.PROJECTION_NAME, name)  # type: ignore[attr-defined]

    async def list_all(self) -> list[GlobalClaudePluginEntry]:
        data = await self._store.get_all(self.PROJECTION_NAME)  # type: ignore[attr-defined]
        return [_entry_from_dict(d) for d in data]

    async def get_by_name(self, name: str) -> GlobalClaudePluginEntry | None:
        data = await self._store.get(self.PROJECTION_NAME, name)  # type: ignore[attr-defined]
        if data is None:
            return None
        return _entry_from_dict(data)


def _entry_to_dict(entry: GlobalClaudePluginEntry) -> dict[str, Any]:
    return {
        "name": entry.name,
        "source_url": entry.source_url,
        "version": entry.version,
        "resolved_sha": entry.resolved_sha,
        "added_at": entry.added_at.isoformat(),
    }


def _entry_from_dict(data: dict[str, Any]) -> GlobalClaudePluginEntry:
    return GlobalClaudePluginEntry(
        name=str(data["name"]),
        source_url=str(data.get("source_url", "")),
        version=str(data.get("version", "")),
        resolved_sha=str(data.get("resolved_sha", "")),
        added_at=_coerce_datetime(data.get("added_at")),
    )


def _coerce_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return datetime.fromtimestamp(0, tz=UTC)
