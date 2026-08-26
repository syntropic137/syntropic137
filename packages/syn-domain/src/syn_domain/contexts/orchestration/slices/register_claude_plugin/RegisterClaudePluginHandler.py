# See ADR-066: this slice handler runs in syn-api but does no I/O beyond the
# storage and registration repository ports, per the thin-API rule. The CLI
# performs the git clone locally and uploads the tree contents in a single
# JSON POST; this handler only validates, hashes, persists, and dispatches.
"""RegisterClaudePlugin command handler (issue #726).

Phase A redesign: the handler no longer talks to a fetcher. The caller
(``POST /claude-plugins/registrations`` route) provides the tree contents
inline, having performed the git clone client-side. Steps:

1. Compute the deterministic stream id for ``(source_url, version)``.
2. Idempotency: if the aggregate already exists, return its data unchanged
   without re-uploading the tree.
3. Otherwise: validate the plugin manifest (``.claude-plugin/plugin.json``),
   compute a content sha over the normalized tree, upload to storage (skipping
   the upload if the sha is already present), then dispatch a
   ``RegisterClaudePluginCommand`` to a fresh aggregate.
4. Concurrent-register safety: ``save_new`` may raise
   ``StreamAlreadyExistsError`` if a parallel request beat us; load the
   existing aggregate and return its data instead of failing.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from event_sourcing import StreamAlreadyExistsError

from syn_domain.contexts.orchestration._shared.claude_plugin_errors import (
    ClaudePluginInvalidPath,
    ClaudePluginManifestInvalid,
    ClaudePluginManifestMissing,
    ClaudePluginVersionHashMismatch,
)
from syn_domain.contexts.orchestration.domain.aggregate_claude_plugin_registration.ClaudePluginRegistrationAggregate import (
    ClaudePluginRegistrationAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.RegisterClaudePluginCommand import (
    RegisterClaudePluginCommand,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.ports.ClaudePluginRegistrationRepositoryPort import (
        ClaudePluginRegistrationRepositoryPort,
    )
    from syn_domain.contexts.orchestration.ports.ClaudePluginStoragePort import (
        ClaudePluginFile,
        ClaudePluginStoragePort,
    )

logger = logging.getLogger(__name__)

_MANIFEST_PATH = ".claude-plugin/plugin.json"


@dataclass(frozen=True)
class RegisterClaudePluginResult:
    """Returned to the caller; mirrors what the lock projection will hold."""

    name: str
    source_url: str
    version: str
    resolved_sha: str
    tree_storage_prefix: str


class RegisterClaudePluginHandler:
    """Handler for the register-claude-plugin slice."""

    def __init__(
        self,
        storage: ClaudePluginStoragePort,
        repo: ClaudePluginRegistrationRepositoryPort,
    ) -> None:
        self._storage = storage
        self._repo = repo

    async def handle(
        self,
        source_url: str,
        version: str,
        name: str | None,
        manifest: dict[str, object],
        files: list[ClaudePluginFile],
    ) -> RegisterClaudePluginResult:
        """Persist the registration of a pre-uploaded plugin tree.

        Args:
            source_url: Canonical URL of the plugin source (e.g. github URL).
            version: Pinned version (tag, branch name, or commit sha).
            name: Caller-supplied display name override; when ``None`` the
                manifest's ``name`` field wins, falling back to a basename.
            manifest: Pre-parsed ``.claude-plugin/plugin.json`` contents. The
                handler still re-validates the manifest is present in the file
                list and matches the supplied dict for defense-in-depth.
            files: Every file in the plugin tree (including the manifest).

        Returns:
            The lock-entry data, idempotent on re-submission of the same
            ``(source_url, version, name)``.
        """
        # WHY first (issue #726 review): rel_path values are caller-controlled
        # and later materialized into workspace paths. A hostile path must be
        # rejected BEFORE anything is hashed, stored, or persisted.
        _validate_tree_paths(files)

        merged_manifest = _build_merged_manifest(files, source_url, version, manifest)
        effective_name = _resolve_effective_name(name, merged_manifest, source_url)

        stream_id = ClaudePluginRegistrationAggregate.compute_stream_id(
            source_url, version, effective_name
        )

        # WHY a ``sha256-<hash>`` version is checked at all: it is a content
        # commitment, not a label. Nothing else enforces it, so without this a
        # caller registers arbitrary content under a version naming another
        # tree's hash, and every later install resolving that triple silently
        # receives the substituted content.
        #
        # WHY before the idempotency short-circuit: submitting different bytes
        # against an EXISTING honest pin would otherwise hit the fast path and
        # be reported as a successful registration, when what actually happened
        # is that the submitted content was discarded. The caller is told their
        # content is installed while the stored tree is someone else's.
        pinned = _declared_hash(version)
        sha = _compute_tree_sha(files) if pinned is not None else None
        if sha is not None:
            _reject_hash_version_mismatch(version, sha, source_url)

        # Fast path: the aggregate already exists. Idempotent re-register.
        existing = await self._repo.get_by_id(stream_id)
        if existing is not None:
            # WHY the STORED sha is re-checked, not just the submitted one:
            # a record written before this guard existed can carry a pinned
            # version whose resolved_sha does not match it. Returning it here
            # would keep serving that substituted content forever, and an
            # honest re-registration would launder it back into circulation.
            if pinned is not None and existing.resolved_sha != pinned:
                raise ClaudePluginVersionHashMismatch(source_url, version, existing.resolved_sha)
            return _result_from_aggregate(existing)

        # Ordinary versions are hashed only once the fast path has missed, so a
        # duplicate re-register of a tag or branch does not rehash the tree.
        if sha is None:
            sha = _compute_tree_sha(files)

        tree_prefix = await self._ensure_tree_uploaded(sha, files)

        command = RegisterClaudePluginCommand(
            aggregate_id=stream_id,
            source_url=source_url,
            version=version,
            resolved_sha=sha,
            name=effective_name,
            tree_storage_prefix=tree_prefix,
            manifest=merged_manifest,
        )

        aggregate = ClaudePluginRegistrationAggregate()
        aggregate.register(command)
        race_result = await self._save_or_recover_from_race(aggregate, stream_id, source_url)
        if race_result is not None:
            return race_result

        return RegisterClaudePluginResult(
            name=effective_name,
            source_url=source_url,
            version=version,
            resolved_sha=sha,
            tree_storage_prefix=tree_prefix,
        )

    async def _ensure_tree_uploaded(
        self,
        sha: str,
        files: list[ClaudePluginFile],
    ) -> str:
        # WHY (issue #726): cache hit reuses the existing prefix via the
        # storage port instead of re-uploading.
        if not await self._storage.exists(sha):
            stored = await self._storage.upload_tree(sha, files)
            return stored.storage_prefix
        return self._storage.prefix_for(sha)

    async def _save_or_recover_from_race(
        self,
        aggregate: ClaudePluginRegistrationAggregate,
        stream_id: str,
        source_url: str,
    ) -> RegisterClaudePluginResult | None:
        """Save the aggregate; on concurrent-write loss, return the winner.

        Returns ``None`` if our save succeeded (caller continues normally);
        returns the winner's result if a concurrent register beat us.
        """
        try:
            await self._repo.save_new(aggregate)
        except StreamAlreadyExistsError:
            logger.info(
                "Concurrent claude plugin register collision; loading existing entry",
                extra={"stream_id": stream_id, "source_url": source_url},
            )
            existing_after = await self._repo.get_by_id(stream_id)
            if existing_after is None:
                # Defensive: the stream exists but we cannot load it.
                msg = (
                    f"StreamAlreadyExistsError for {stream_id} but get_by_id "
                    f"returned None - investigate event store state"
                )
                raise RuntimeError(msg) from None
            return _result_from_aggregate(existing_after)
        return None


def _rel_path_segment_problem(rel_path: str) -> str | None:
    for segment in rel_path.split("/"):
        if segment == "":
            return "path contains an empty segment"
        if segment in (".", ".."):
            return f"path contains a {segment!r} segment"
    return None


def _rel_path_problem(rel_path: str) -> str | None:
    """Return a human-readable reason if ``rel_path`` is unsafe, else ``None``.

    Rules (issue #726 review): POSIX-relative only -- no leading slash, no
    backslash, no NUL/control characters, and no empty / ``.`` / ``..``
    segments. These paths are stored verbatim and later joined under
    ``.syn-plugins/<name>/`` in workspaces, so anything that could escape
    that prefix (or smuggle separators past docker-cp) is rejected outright.
    """
    if not rel_path.strip():
        return "path is empty"
    if rel_path.startswith("/"):
        return "path is absolute"
    if "\\" in rel_path:
        return "path contains a backslash"
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in rel_path):
        return "path contains control characters"
    return _rel_path_segment_problem(rel_path)


def _validate_tree_paths(files: list[ClaudePluginFile]) -> None:
    """Reject the whole registration on the first unsafe ``rel_path``."""
    for f in files:
        reason = _rel_path_problem(f.rel_path)
        if reason is not None:
            raise ClaudePluginInvalidPath(f.rel_path, reason)


def _build_merged_manifest(
    files: list[ClaudePluginFile],
    source_url: str,
    version: str,
    caller_manifest: dict[str, object],
) -> dict[str, object]:
    """Parse the manifest from the file tree, merging with the caller's view.

    WHY merge: the inline ``manifest`` argument lets the CLI carry through
    fields it parsed locally, but the file-derived parse is authoritative.
    Identical content for identical input; the merge guards against drift.
    """
    parsed_manifest = _extract_plugin_manifest(files, source_url, version)
    return {**caller_manifest, **parsed_manifest}


def _resolve_effective_name(
    explicit_name: str | None,
    merged_manifest: dict[str, object],
    source_url: str,
) -> str:
    """Determine the canonical plugin name.

    WHY priority order: caller-supplied ``name`` is authoritative when set,
    then the manifest's name, then a basename fallback. The stream id includes
    the name, so this must be resolved BEFORE the stream id is computed.
    """
    manifest_name = _name_from_manifest(merged_manifest)
    default_name = explicit_name if explicit_name else manifest_name
    return default_name or _basename_from_url(source_url)


def _compute_tree_sha(files: list[ClaudePluginFile]) -> str:
    """SHA-256 over (sorted rel_path, content) pairs.

    Why sort: same logical tree must hash identically regardless of the order
    the caller submitted files in.
    """
    hasher = hashlib.sha256()
    for f in sorted(files, key=lambda x: x.rel_path):
        hasher.update(f.rel_path.encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(f.content)
        hasher.update(b"\x00")
    return hasher.hexdigest()


def _extract_plugin_manifest(
    files: list[ClaudePluginFile],
    source_url: str,
    version: str,
) -> dict[str, object]:
    """Read and validate ``.claude-plugin/plugin.json`` from the tree.

    WHY ``dict[str, object]`` (issue #726): real ``plugin.json`` files contain
    arrays and nested objects. Manifest is treated as opaque metadata downstream;
    widening the value type preserves the original shape.
    """
    manifest_file = next((f for f in files if f.rel_path == _MANIFEST_PATH), None)
    if manifest_file is None:
        raise ClaudePluginManifestMissing(source_url, version)
    try:
        parsed = json.loads(manifest_file.content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClaudePluginManifestInvalid(source_url, version, str(exc)) from exc
    if not isinstance(parsed, dict):
        raise ClaudePluginManifestInvalid(source_url, version, "plugin.json must be a JSON object")
    # WHY copy with str-key filter: JSON keys are always strings, but the
    # parsed value comes back typed as ``dict[Any, Any]``.
    return {str(key): value for key, value in parsed.items() if isinstance(key, str)}


def _name_from_manifest(manifest: dict[str, object]) -> str:
    """Return ``manifest['name']`` as a clean string, or empty if missing."""
    name_value = manifest.get("name")
    if isinstance(name_value, str) and name_value.strip():
        return name_value.strip()
    return ""


def _basename_from_url(source_url: str) -> str:
    """Last path segment of the source URL (minus a ``.git`` suffix).

    Used as the final fallback display name when neither the request body nor
    the manifest provided one. Mirrors the CLI ``parseClaudePluginRef`` default
    so the lock entry's display name is stable regardless of which side picked
    it.
    """
    tail = source_url.rstrip("/")
    for sep in ("/", ":"):
        idx = tail.rfind(sep)
        if idx >= 0:
            tail = tail[idx + 1 :]
            break
    if tail.endswith(".git"):
        tail = tail[:-4]
    return tail or source_url


def _result_from_aggregate(
    aggregate: ClaudePluginRegistrationAggregate,
) -> RegisterClaudePluginResult:
    if (
        aggregate.source_url is None
        or aggregate.plugin_version is None
        or aggregate.resolved_sha is None
        or aggregate.name is None
        or aggregate.tree_storage_prefix is None
    ):
        msg = (
            "ClaudePluginRegistrationAggregate is missing required fields - "
            "aggregate replay produced an empty state"
        )
        raise RuntimeError(msg)
    return RegisterClaudePluginResult(
        name=aggregate.name,
        source_url=aggregate.source_url,
        version=aggregate.plugin_version,
        resolved_sha=aggregate.resolved_sha,
        tree_storage_prefix=aggregate.tree_storage_prefix,
    )


_HASH_VERSION_PREFIX = "sha256-"


def _declared_hash(version: str) -> str | None:
    """The hash a ``sha256-<hash>`` version commits to, or None if unpinned."""
    if not version.startswith(_HASH_VERSION_PREFIX):
        return None
    return version[len(_HASH_VERSION_PREFIX) :]


def _reject_hash_version_mismatch(version: str, actual_sha: str, source_url: str) -> None:
    """Enforce that a ``sha256-<hash>`` version names the content it carries."""
    declared = _declared_hash(version)
    if declared is None:
        return
    if declared != actual_sha:
        raise ClaudePluginVersionHashMismatch(source_url, version, actual_sha)
