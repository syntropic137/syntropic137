"""Skill lock projection (issue #772).

Read model keyed by ``(source_url, version, skill_name)``. Built from
``SkillRegisteredEvent``. The resolution service queries this projection to
decide whether a workflow's skills refs are already fetched +
content-addressed (cache hit) or need a fresh registration (miss).

Why ``skill_name`` is part of the primary key: marketplace repos host
multiple skills at the same (source_url, version). Keying on
(source_url, version) alone collapses every marketplace skill to one row and
the first skill registered shadows the rest. See the aggregate's stream-id
helper for the same reasoning. Mirrors ``ClaudePluginLockProjection`` (issue
#726).

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
class SkillLockEntry:
    """Lock projection row mirroring the aggregate fields.

    Identity is ``(source_url, version, skill_name)``. The same skill name
    from the same marketplace source at the same version is treated as one
    entry; re-registering is idempotent. Different skills in the same
    marketplace repo get separate rows.
    """

    skill_name: str
    source_url: str
    version: str
    resolved_sha: str
    tree_storage_prefix: str
    registered_at: datetime


def _lock_key(source_url: str, version: str, skill_name: str) -> str:
    """Composite primary key for the lock store. Stable across restarts.

    See the SkillLockEntry / aggregate docs for why ``skill_name`` is in the
    key.
    """
    return f"{source_url}|{version}|{skill_name}"


class SkillLockProjection(AutoDispatchProjection):
    """Lock-table read model for registered skills.

    Stored under projection name ``skill_lock``. Two indices:
      - primary: ``(source_url, version, skill_name)`` via ``_lock_key``
      - secondary (in-memory at read time): ``(skill_name, version)`` via
        list scan

    A secondary store-backed (skill_name, version) index is unnecessary
    because the expected total row count is small (tens to low hundreds) -
    scanning is fine.
    """

    PROJECTION_NAME = "skill_lock"
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

    async def on_skill_registered(self, event_data: dict[str, Any]) -> None:
        """Persist a registered skill lock entry."""
        source_url = event_data.get("source_url")
        version = event_data.get("version")
        skill_name = event_data.get("skill_name")
        if (
            not isinstance(source_url, str)
            or not isinstance(version, str)
            or not isinstance(skill_name, str)
            or not skill_name
        ):
            return
        registered_at_raw = event_data.get("registered_at")
        registered_at = _coerce_datetime(registered_at_raw)
        entry = SkillLockEntry(
            source_url=source_url,
            version=version,
            skill_name=skill_name,
            resolved_sha=str(event_data.get("resolved_sha", "")),
            tree_storage_prefix=str(event_data.get("tree_storage_prefix", "")),
            registered_at=registered_at,
        )
        await self._save(entry)

    async def get(
        self,
        source_url: str,
        version: str,
        skill_name: str,
    ) -> SkillLockEntry | None:
        """Primary-key lookup for the (source_url, version, skill_name) triple."""
        data = await self._store.get(  # type: ignore[attr-defined]
            self.PROJECTION_NAME,
            _lock_key(source_url, version, skill_name),
        )
        if data is None:
            return None
        return _entry_from_dict(data)

    async def list_all(self) -> list[SkillLockEntry]:
        data = await self._store.get_all(self.PROJECTION_NAME)  # type: ignore[attr-defined]
        return [_entry_from_dict(d) for d in data]

    async def get_by_name_version(
        self,
        skill_name: str,
        version: str,
    ) -> SkillLockEntry | None:
        """Linear scan by display-name + version. See class docstring."""
        for entry in await self.list_all():
            if entry.skill_name == skill_name and entry.version == version:
                return entry
        return None

    async def _save(self, entry: SkillLockEntry) -> None:
        await self._store.save(  # type: ignore[attr-defined]
            self.PROJECTION_NAME,
            _lock_key(entry.source_url, entry.version, entry.skill_name),
            _entry_to_dict(entry),
        )


def _entry_to_dict(entry: SkillLockEntry) -> dict[str, Any]:
    return {
        "source_url": entry.source_url,
        "version": entry.version,
        "skill_name": entry.skill_name,
        "resolved_sha": entry.resolved_sha,
        "tree_storage_prefix": entry.tree_storage_prefix,
        "registered_at": entry.registered_at.isoformat(),
    }


def _entry_from_dict(data: dict[str, Any]) -> SkillLockEntry:
    return SkillLockEntry(
        source_url=str(data["source_url"]),
        version=str(data["version"]),
        skill_name=str(data.get("skill_name", "")),
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
