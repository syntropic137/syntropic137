"""MinIO skill tree storage adapter (issue #772).

Stores skill trees in MinIO under sha256-keyed prefixes:

    skills/sha256-<hash>/files/<rel-path>

A `manifest.json` is written alongside each tree under the same prefix so
re-fetches can enumerate the file list without scanning the bucket.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.ports.SkillStoragePort import (
    SkillFile,
    SkillStorageStats,
    StoredSkillTree,
)

if TYPE_CHECKING:
    from syn_adapters.object_storage.minio import MinioStorage

logger = logging.getLogger(__name__)

_MANIFEST_KEY = "manifest.json"

# Ceiling on a single stats listing. Skill trees are small and few, so this is
# far above any realistic store; exceeding it sets ``truncated`` rather than
# silently reporting a partial total as a complete one.
_STATS_MAX_KEYS = 100_000


def _tree_id_from_key(key: str, prefix: str) -> str | None:
    """Extract the ``sha256-<hash>`` segment from an object key, if present."""
    head = f"{prefix}/"
    if not key.startswith(head):
        return None
    segment = key[len(head) :].split("/", 1)[0]
    return segment if segment.startswith("sha256-") else None


class SkillStorageError(Exception):
    """Raised when a skill storage operation fails."""


class MinioSkillStorage:
    """MinIO-backed skill tree storage.

    Implements ``SkillStoragePort`` using MinIO. Tree files are
    uploaded individually; a manifest.json records the file list so
    fetches don't need to enumerate the bucket.
    """

    def __init__(
        self,
        minio_storage: MinioStorage,
        *,
        prefix: str = "skills",
    ) -> None:
        self._storage = minio_storage
        self._prefix = prefix

    def _tree_prefix(self, sha256: str) -> str:
        return f"{self._prefix}/sha256-{sha256}"

    def prefix_for(self, sha256: str) -> str:
        """Public accessor for the sha256-keyed storage prefix (issue #772).

        WHY: lets the registration handler reconstruct the prefix on a cache
        hit (``exists(sha256) is True``) without re-uploading the tree.
        """
        return self._tree_prefix(sha256)

    def _file_key(self, sha256: str, rel_path: str) -> str:
        return f"{self._tree_prefix(sha256)}/files/{rel_path}"

    def _manifest_key(self, sha256: str) -> str:
        return f"{self._tree_prefix(sha256)}/{_MANIFEST_KEY}"

    async def upload_tree(
        self,
        sha256: str,
        files: list[SkillFile],
    ) -> StoredSkillTree:
        """Upload every file in the tree under the sha256-keyed prefix."""
        if not files:
            msg = "Cannot upload empty skill tree"
            raise SkillStorageError(msg)

        total_bytes = 0
        manifest_entries: list[dict[str, str | int]] = []

        for f in files:
            key = self._file_key(sha256, f.rel_path)
            try:
                await self._storage.upload(key, f.content)
            except Exception as e:
                logger.error(
                    "Failed to upload skill file",
                    extra={"sha256": sha256, "rel_path": f.rel_path, "error": str(e)},
                )
                msg = f"Upload failed for {f.rel_path}: {e}"
                raise SkillStorageError(msg) from e
            total_bytes += len(f.content)
            manifest_entries.append({"rel_path": f.rel_path, "size_bytes": len(f.content)})

        manifest = {
            "sha256": sha256,
            "file_count": len(files),
            "total_size_bytes": total_bytes,
            "files": manifest_entries,
        }
        try:
            await self._storage.upload(
                self._manifest_key(sha256),
                json.dumps(manifest, sort_keys=True).encode("utf-8"),
                content_type="application/json",
            )
        except Exception as e:
            msg = f"Manifest upload failed: {e}"
            raise SkillStorageError(msg) from e

        logger.info(
            "Skill tree uploaded",
            extra={
                "sha256": sha256,
                "prefix": self._tree_prefix(sha256),
                "file_count": len(files),
                "total_size_bytes": total_bytes,
            },
        )

        return StoredSkillTree(
            storage_prefix=self._tree_prefix(sha256),
            sha256=sha256,
            file_count=len(files),
            total_size_bytes=total_bytes,
            metadata={"bucket": self._storage.bucket_name},
        )

    async def fetch_tree(self, sha256: str) -> list[SkillFile]:
        """Read every file in the tree from storage by reading the manifest first."""
        try:
            manifest_bytes = await self._storage.download(self._manifest_key(sha256))
        except Exception as e:
            msg = f"No skill tree found for sha256={sha256}: {e}"
            raise SkillStorageError(msg) from e

        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except Exception as e:
            msg = f"Corrupt manifest for sha256={sha256}: {e}"
            raise SkillStorageError(msg) from e

        files: list[SkillFile] = []
        for entry in manifest.get("files", []):
            rel_path = entry["rel_path"]
            content = await self._storage.download(self._file_key(sha256, rel_path))
            files.append(SkillFile(rel_path=rel_path, content=content))

        return files

    async def exists(self, sha256: str) -> bool:
        """Check if a tree with this sha256 has been uploaded (manifest present)."""
        try:
            await self._storage.download(self._manifest_key(sha256))
            return True
        except Exception:
            return False

    async def stats(self) -> SkillStorageStats:
        """Sum object sizes under the skills prefix (issue #772, spec D6).

        ``skill_count`` counts distinct ``skills/sha256-*`` prefixes, not
        files, since one skill tree is many objects plus a manifest.

        A truncated listing is reported rather than hidden: the counts would
        otherwise read as complete totals when they are lower bounds.
        """
        result = await self._storage.list_objects(f"{self._prefix}/", max_keys=_STATS_MAX_KEYS)

        trees: set[str] = set()
        total_bytes = 0
        for obj in result.objects:
            total_bytes += obj.size_bytes
            tree = _tree_id_from_key(obj.key, self._prefix)
            if tree is not None:
                trees.add(tree)

        if result.is_truncated:
            logger.warning(
                "Skill storage listing truncated at %d objects; stats are lower bounds",
                _STATS_MAX_KEYS,
            )

        return SkillStorageStats(
            object_count=len(result.objects),
            total_bytes=total_bytes,
            skill_count=len(trees),
            truncated=result.is_truncated,
        )

    async def ensure_ready(self) -> None:
        """Ensure the underlying storage backend is ready (bucket exists)."""
        await self._storage.ensure_ready()
