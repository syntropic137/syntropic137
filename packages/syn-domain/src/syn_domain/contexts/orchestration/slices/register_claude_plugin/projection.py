"""Claude plugin lock projection (issue #726).

Read model keyed by ``(source_url, version, name)``. Built from
``ClaudePluginRegisteredEvent``. The Phase 5 resolution service queries this
projection to decide whether a workflow's claude_plugins refs are already
fetched + content-addressed (cache hit) or need a fresh registration (miss).

Why ``name`` is part of the primary key: marketplace repos host multiple
plugins at the same (source_url, version). Keying on (source_url, version)
alone collapses every marketplace plugin to one row and the first plugin
registered shadows the rest. See the aggregate's stream-id helper for the
same reasoning.

Why a separate projection instead of querying the aggregate stream: the
projection lets the API layer answer "is this ref registered?" with one
read against a small index, instead of computing the deterministic stream
id and then loading the aggregate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from event_sourcing import AutoDispatchProjection


@dataclass(frozen=True)
class LockEntry:
    """Lock projection row mirroring the aggregate fields.

    Identity is ``(source_url, version, name)``. The same plugin name from
    the same marketplace source at the same version is treated as one entry;
    re-registering is idempotent. Different plugins in the same marketplace
    (sdlc vs workspace under agentic-primitives@main) get separate rows.
    """

    source_url: str
    version: str
    name: str
    resolved_sha: str
    tree_storage_prefix: str
    registered_at: datetime


def _lock_key(source_url: str, version: str, name: str) -> str:
    """Composite primary key for the lock store. Stable across restarts.

    See the LockEntry / aggregate docs for why ``name`` is in the key.
    """
    return f"{source_url}|{version}|{name}"


class ClaudePluginLockProjection(AutoDispatchProjection):
    """Lock-table read model for registered claude plugins.

    Stored under projection name ``claude_plugin_lock``. Two indices:
      - primary: ``(source_url, version)`` via ``_lock_key``
      - secondary (in-memory at read time): ``(name, version)`` via list scan

    A secondary store-backed (name, version) index is unnecessary because the
    expected total row count is small (tens to low hundreds) - scanning is fine.
    """

    PROJECTION_NAME = "claude_plugin_lock"
    VERSION = 1

    # Why object: avoid coupling this domain projection to the syn-adapters
    # concrete store class. Production wires a real ``ProjectionStore``; tests
    # wire ``InMemoryProjectionStore``. Both expose the same async surface.
    def __init__(self, store: object) -> None:
        self._store = store

    def get_name(self) -> str:
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        return self.VERSION

    async def clear_all_data(self) -> None:
        if hasattr(self._store, "delete_all"):
            await self._store.delete_all(self.PROJECTION_NAME)  # type: ignore[attr-defined]

    async def on_claude_plugin_registered(self, event_data: dict[str, Any]) -> None:
        """Persist a registered claude plugin lock entry."""
        source_url = event_data.get("source_url")
        version = event_data.get("version")
        name = event_data.get("name")
        if (
            not isinstance(source_url, str)
            or not isinstance(version, str)
            or not isinstance(name, str)
            or not name
        ):
            return
        registered_at_raw = event_data.get("registered_at")
        registered_at = _coerce_datetime(registered_at_raw)
        entry = LockEntry(
            source_url=source_url,
            version=version,
            name=name,
            resolved_sha=str(event_data.get("resolved_sha", "")),
            tree_storage_prefix=str(event_data.get("tree_storage_prefix", "")),
            registered_at=registered_at,
        )
        await self._save(entry)

    async def get_by_source_version_name(
        self,
        source_url: str,
        version: str,
        name: str,
    ) -> LockEntry | None:
        """Primary-key lookup for the (source_url, version, name) triple."""
        data = await self._store.get(  # type: ignore[attr-defined]
            self.PROJECTION_NAME,
            _lock_key(source_url, version, name),
        )
        if data is None:
            return None
        return _entry_from_dict(data)

    async def list_all(self) -> list[LockEntry]:
        data = await self._store.get_all(self.PROJECTION_NAME)  # type: ignore[attr-defined]
        return [_entry_from_dict(d) for d in data]

    async def get_by_name_version(
        self,
        name: str,
        version: str,
    ) -> LockEntry | None:
        """Linear scan by display-name + version. See class docstring."""
        for entry in await self.list_all():
            if entry.name == name and entry.version == version:
                return entry
        return None

    async def _save(self, entry: LockEntry) -> None:
        await self._store.save(  # type: ignore[attr-defined]
            self.PROJECTION_NAME,
            _lock_key(entry.source_url, entry.version, entry.name),
            _entry_to_dict(entry),
        )


def _entry_to_dict(entry: LockEntry) -> dict[str, Any]:
    return {
        "source_url": entry.source_url,
        "version": entry.version,
        "name": entry.name,
        "resolved_sha": entry.resolved_sha,
        "tree_storage_prefix": entry.tree_storage_prefix,
        "registered_at": entry.registered_at.isoformat(),
    }


def _entry_from_dict(data: dict[str, Any]) -> LockEntry:
    return LockEntry(
        source_url=str(data["source_url"]),
        version=str(data["version"]),
        name=str(data.get("name", "")),
        resolved_sha=str(data.get("resolved_sha", "")),
        tree_storage_prefix=str(data.get("tree_storage_prefix", "")),
        registered_at=_coerce_datetime(data.get("registered_at")),
    )


def _coerce_datetime(value: object) -> datetime:
    """Accept either a datetime or an ISO string from the event store."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    # Why a sentinel: missing timestamps should still produce a valid entry so
    # the lock projection never silently drops a row; downstream code surfaces
    # the anomaly via the obviously-wrong epoch.
    return datetime.fromtimestamp(0, tz=UTC)
