"""Skill workspace materializer (issue #772).

Reads resolved skill trees from object storage and rewrites their relative
paths into the workspace-relative shape the existing
``ManagedWorkspace.inject_files()`` docker-cp path expects:
``.syn-skills/<skill-name>/<file-rel-path>``.

The materialization step is otherwise stateless: this service is
constructed once at startup, holds a per-process LRU cache keyed by the
content-addressed skill sha so multi-phase workflows do not re-fetch the
same trees from MinIO. Cache eviction is bounded so a long-running API
process does not unbounded-grow the heap when many distinct skills are
referenced over its lifetime.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration import (
    SkillInvalidName,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration._shared.resolved_skill import (
        ResolvedSkill,
    )
    from syn_domain.contexts.orchestration.ports.SkillStoragePort import (
        SkillStoragePort,
    )

# WHY: skill.skill_name is interpolated into a workspace path. We must reject
# anything that could escape ``.syn-skills/<skill_name>/`` -- traversal,
# separators, absolute paths, or control characters. Names must be a single
# safe segment.
_FORBIDDEN_NAME_SUBSTRINGS = ("..", "/", "\\", "\x00")


def _validate_skill_name(name: str) -> None:
    """Reject skill names that would be unsafe in a workspace path.

    Raises ``SkillInvalidName`` for empty names, names with path
    separators, parent-directory traversal, leading dots, or control
    characters. The check runs at the materialization boundary so a
    registration that somehow slipped a hostile name through cannot reach
    the workspace.
    """
    if not name or not name.strip():
        raise SkillInvalidName(name, "name is empty")
    if name.startswith("."):
        raise SkillInvalidName(name, "name starts with '.'")
    for needle in _FORBIDDEN_NAME_SUBSTRINGS:
        if needle in name:
            raise SkillInvalidName(name, f"name contains forbidden sequence {needle!r}")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in name):
        raise SkillInvalidName(name, "name contains control characters")


# WHY: 16 entries comfortably covers a typical workflow's skill set across
# phases without bounding heap usage. Each entry is the file-byte tuple list
# for one skill tree (kilobytes to a few MB at the high end).
_DEFAULT_CACHE_SIZE = 16

# WHY: directory under the workspace root that mirrors the validated
# experiment shape ``<workspace>/.syn-skills/<skill_name>/`` and matches the
# skill installation path the orchestrator emits.
WORKSPACE_SKILL_ROOT = ".syn-skills"


class SkillMaterializer:
    """Fetches skill trees and rewrites paths for workspace injection.

    The output of ``fetch_for_workspace`` is the exact ``list[(rel_path, bytes)]``
    shape ``ManagedWorkspace.inject_files()`` expects, so the caller can pass
    it through unmodified.
    """

    def __init__(
        self,
        storage: SkillStoragePort,
        cache_size: int = _DEFAULT_CACHE_SIZE,
    ) -> None:
        self._storage = storage
        self._cache_size = cache_size
        # WHY OrderedDict: ``move_to_end`` plus ``popitem(last=False)`` gives
        # textbook LRU eviction without pulling in a third-party dependency.
        self._cache: OrderedDict[str, tuple[tuple[str, bytes], ...]] = OrderedDict()

    async def fetch_for_workspace(
        self,
        skills: tuple[ResolvedSkill, ...],
    ) -> list[tuple[str, bytes]]:
        """Return ``[(workspace_rel_path, content), ...]`` for every skill file.

        Paths are prefixed with ``.syn-skills/<skill.skill_name>/``. The order
        of files is whatever the underlying storage returned, which is fine
        because ``inject_files`` does not require any ordering guarantees.
        """
        if not skills:
            return []
        # WHY: validate every name BEFORE any fetch -- a hostile name must not
        # cause partial materialization. Raises SkillInvalidName and writes
        # nothing on the first bad name.
        for skill in skills:
            _validate_skill_name(skill.skill_name)
        materialized: list[tuple[str, bytes]] = []
        for skill in skills:
            tree = await self._fetch_tree_cached(skill.resolved_sha)
            for rel_path, content in tree:
                materialized.append(
                    (f"{WORKSPACE_SKILL_ROOT}/{skill.skill_name}/{rel_path}", content)
                )
        return materialized

    async def _fetch_tree_cached(self, sha256: str) -> tuple[tuple[str, bytes], ...]:
        """Cache-aware wrapper over ``storage.fetch_tree``.

        WHY immutable tuples: callers receive the cached object directly; tuples
        prevent accidental mutation of cached entries from leaking into other
        workspaces.
        """
        cached = self._cache.get(sha256)
        if cached is not None:
            self._cache.move_to_end(sha256)
            return cached
        files = await self._storage.fetch_tree(sha256)
        snapshot: tuple[tuple[str, bytes], ...] = tuple((f.rel_path, f.content) for f in files)
        self._cache[sha256] = snapshot
        if len(self._cache) > self._cache_size:
            # WHY popitem(last=False): evict the least-recently-used entry.
            self._cache.popitem(last=False)
        return snapshot

    def cache_size(self) -> int:
        """Return current cache occupancy. Test-only observability hook."""
        return len(self._cache)
