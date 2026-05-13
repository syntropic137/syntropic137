"""ShowClaudePlugin query handler (issue #726).

Single-entry lookup by ``(name, version)`` over the lock projection. The lock
is keyed by ``(source_url, version)`` for hash-collision-safe identity, but
the user-facing CLI queries by display name; we scan the small projection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.slices.register_claude_plugin.projection import (
        ClaudePluginLockProjection,
        LockEntry,
    )


class ClaudePluginNotFoundError(Exception):
    """Raised when the lock has no entry matching the (name, version) pair."""

    def __init__(self, name: str, version: str) -> None:
        super().__init__(f"Claude plugin not found: {name}@{version}")
        self.name = name
        self.version = version


class ShowClaudePluginHandler:
    def __init__(self, projection: ClaudePluginLockProjection) -> None:
        self._projection = projection

    async def handle(self, name: str, version: str) -> LockEntry:
        entry = await self._projection.get_by_name_version(name, version)
        if entry is None:
            raise ClaudePluginNotFoundError(name, version)
        return entry
