"""MinIO claude plugin tree storage adapter (issue #726).

Stores plugin trees in MinIO under sha256-keyed prefixes:

    claude-plugins/sha256-<hash>/<rel-path>

A `manifest.json` is written alongside each tree under the same prefix so
re-fetches can enumerate the file list without scanning the bucket.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.ports.ClaudePluginStoragePort import (
    ClaudePluginFile,
    StoredClaudePluginTree,
)

if TYPE_CHECKING:
    from syn_adapters.object_storage.minio import MinioStorage

logger = logging.getLogger(__name__)

_MANIFEST_KEY = "manifest.json"


class ClaudePluginStorageError(Exception):
    """Raised when a claude plugin storage operation fails."""


class MinioClaudePluginStorage:
    """MinIO-backed claude plugin tree storage.

    Implements ``ClaudePluginStoragePort`` using MinIO. Tree files are
    uploaded individually; a manifest.json records the file list so
    fetches don't need to enumerate the bucket.
    """

    def __init__(
        self,
        minio_storage: MinioStorage,
        *,
        prefix: str = "claude-plugins",
    ) -> None:
        self._storage = minio_storage
        self._prefix = prefix

    def _tree_prefix(self, sha256: str) -> str:
        return f"{self._prefix}/sha256-{sha256}"

    def prefix_for(self, sha256: str) -> str:
        """Public accessor for the sha256-keyed storage prefix (issue #726).

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
        files: list[ClaudePluginFile],
    ) -> StoredClaudePluginTree:
        """Upload every file in the tree under the sha256-keyed prefix."""
        if not files:
            msg = "Cannot upload empty claude plugin tree"
            raise ClaudePluginStorageError(msg)

        total_bytes = 0
        manifest_entries: list[dict[str, str | int]] = []

        for f in files:
            key = self._file_key(sha256, f.rel_path)
            try:
                await self._storage.upload(key, f.content)
            except Exception as e:
                logger.error(
                    "Failed to upload claude plugin file",
                    extra={"sha256": sha256, "rel_path": f.rel_path, "error": str(e)},
                )
                msg = f"Upload failed for {f.rel_path}: {e}"
                raise ClaudePluginStorageError(msg) from e
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
            raise ClaudePluginStorageError(msg) from e

        logger.info(
            "Claude plugin tree uploaded",
            extra={
                "sha256": sha256,
                "prefix": self._tree_prefix(sha256),
                "file_count": len(files),
                "total_size_bytes": total_bytes,
            },
        )

        return StoredClaudePluginTree(
            storage_prefix=self._tree_prefix(sha256),
            sha256=sha256,
            file_count=len(files),
            total_size_bytes=total_bytes,
            metadata={"bucket": self._storage.bucket_name},
        )

    async def fetch_tree(self, sha256: str) -> list[ClaudePluginFile]:
        """Read every file in the tree from storage by reading the manifest first."""
        try:
            manifest_bytes = await self._storage.download(self._manifest_key(sha256))
        except Exception as e:
            msg = f"No claude plugin tree found for sha256={sha256}: {e}"
            raise ClaudePluginStorageError(msg) from e

        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except Exception as e:
            msg = f"Corrupt manifest for sha256={sha256}: {e}"
            raise ClaudePluginStorageError(msg) from e

        files: list[ClaudePluginFile] = []
        for entry in manifest.get("files", []):
            rel_path = entry["rel_path"]
            content = await self._storage.download(self._file_key(sha256, rel_path))
            files.append(ClaudePluginFile(rel_path=rel_path, content=content))

        return files

    async def exists(self, sha256: str) -> bool:
        """Check if a tree with this sha256 has been uploaded (manifest present)."""
        try:
            await self._storage.download(self._manifest_key(sha256))
            return True
        except Exception:
            return False

    async def ensure_ready(self) -> None:
        """Ensure the underlying storage backend is ready (bucket exists)."""
        await self._storage.ensure_ready()
