# See ADR-066: this slice handler runs in syn-api but does no I/O beyond the
# storage and registration repository ports, per the thin-API rule. The CLI
# performs the git clone locally and uploads the tree contents in a single
# JSON POST; this handler only validates, hashes, persists, and dispatches.
"""RegisterSkill command handler (issue #772).

The handler does not talk to a fetcher. The caller
(``POST /skills/registrations`` route) provides the tree contents inline,
having performed the git clone client-side. Steps:

1. Compute the deterministic stream id for ``(source_url, version, skill_name)``.
2. Idempotency: if the aggregate already exists, return its data unchanged
   without re-uploading the tree.
3. Otherwise: validate the SKILL.md frontmatter, compute a content sha over
   the normalized tree, upload to storage (skipping the upload if the sha is
   already present), then dispatch a ``RegisterSkillCommand`` to a fresh
   aggregate.
4. Concurrent-register safety: ``save_new`` may raise
   ``StreamAlreadyExistsError`` if a parallel request beat us; load the
   existing aggregate and return its data instead of failing.

Mirrors ``RegisterClaudePluginHandler`` (issue #726). The one semantic
difference: the manifest is always the tree's root ``SKILL.md`` frontmatter
(no caller-supplied manifest argument), per the vercel-labs/skills convention.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import yaml
from event_sourcing import StreamAlreadyExistsError

from syn_domain.contexts.orchestration._shared.skill_errors import (
    SkillInvalidPath,
    SkillManifestInvalid,
    SkillManifestMissing,
)
from syn_domain.contexts.orchestration.domain.aggregate_skill_registration.SkillRegistrationAggregate import (
    SkillRegistrationAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.RegisterSkillCommand import (
    RegisterSkillCommand,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration._shared.skill_ref import SkillManifest
    from syn_domain.contexts.orchestration.ports.SkillRegistrationRepositoryPort import (
        SkillRegistrationRepositoryPort,
    )
    from syn_domain.contexts.orchestration.ports.SkillStoragePort import (
        SkillFile,
        SkillStoragePort,
    )

logger = logging.getLogger(__name__)

_MANIFEST_PATH = "SKILL.md"
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass(frozen=True)
class RegisterSkillResult:
    """Returned to the caller; mirrors what the lock projection will hold."""

    skill_name: str
    source_url: str
    version: str
    resolved_sha: str
    tree_storage_prefix: str


class RegisterSkillHandler:
    """Handler for the register-skill slice."""

    def __init__(
        self,
        storage: SkillStoragePort,
        repo: SkillRegistrationRepositoryPort,
    ) -> None:
        self._storage = storage
        self._repo = repo

    async def handle(
        self,
        source_url: str,
        version: str,
        skill_name: str | None,
        files: list[SkillFile],
    ) -> RegisterSkillResult:
        """Persist the registration of a pre-uploaded skill tree.

        Args:
            source_url: Canonical URL of the skill source (e.g. github URL).
            version: Pinned version (tag, branch name, or commit sha).
            skill_name: Caller-supplied display name override; when ``None``
                the SKILL.md frontmatter's ``name`` field wins, falling back
                to a basename.
            files: Every file in the skill tree (including SKILL.md).

        Returns:
            The lock-entry data, idempotent on re-submission of the same
            ``(source_url, version, skill_name)``.
        """
        # WHY first (mirrors #726 review): rel_path values are caller-
        # controlled and later materialized into workspace paths. A hostile
        # path must be rejected BEFORE anything is hashed, stored, or
        # persisted.
        _validate_tree_paths(files)

        frontmatter = _extract_skill_frontmatter(files, source_url, version)
        effective_name = _resolve_effective_name(skill_name, frontmatter, source_url)

        stream_id = SkillRegistrationAggregate.compute_stream_id(
            source_url, version, effective_name
        )

        # Fast path: the aggregate already exists. Idempotent re-register.
        existing = await self._repo.get_by_id(stream_id)
        if existing is not None:
            return _result_from_aggregate(existing)

        sha = _compute_tree_sha(files)
        tree_prefix = await self._ensure_tree_uploaded(sha, files)

        command = RegisterSkillCommand(
            aggregate_id=stream_id,
            source_url=source_url,
            version=version,
            resolved_sha=sha,
            skill_name=effective_name,
            tree_storage_prefix=tree_prefix,
            manifest=frontmatter,
        )

        aggregate = SkillRegistrationAggregate()
        aggregate.register(command)
        race_result = await self._save_or_recover_from_race(aggregate, stream_id, source_url)
        if race_result is not None:
            return race_result

        return RegisterSkillResult(
            skill_name=effective_name,
            source_url=source_url,
            version=version,
            resolved_sha=sha,
            tree_storage_prefix=tree_prefix,
        )

    async def _ensure_tree_uploaded(
        self,
        sha: str,
        files: list[SkillFile],
    ) -> str:
        # WHY (issue #772): cache hit reuses the existing prefix via the
        # storage port instead of re-uploading.
        if not await self._storage.exists(sha):
            stored = await self._storage.upload_tree(sha, files)
            return stored.storage_prefix
        return self._storage.prefix_for(sha)

    async def _save_or_recover_from_race(
        self,
        aggregate: SkillRegistrationAggregate,
        stream_id: str,
        source_url: str,
    ) -> RegisterSkillResult | None:
        """Save the aggregate; on concurrent-write loss, return the winner.

        Returns ``None`` if our save succeeded (caller continues normally);
        returns the winner's result if a concurrent register beat us.
        """
        try:
            await self._repo.save_new(aggregate)
        except StreamAlreadyExistsError:
            logger.info(
                "Concurrent skill register collision; loading existing entry",
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

    Rules (mirrors #726 review): POSIX-relative only -- no leading slash, no
    backslash, no NUL/control characters, and no empty / ``.`` / ``..``
    segments. These paths are stored verbatim and later joined under
    ``.syn-skills/<skill_name>/`` in workspaces, so anything that could escape
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


def _validate_tree_paths(files: list[SkillFile]) -> None:
    """Reject the whole registration on the first unsafe ``rel_path``."""
    for f in files:
        reason = _rel_path_problem(f.rel_path)
        if reason is not None:
            raise SkillInvalidPath(f.rel_path, reason)


def _resolve_effective_name(
    explicit_name: str | None,
    frontmatter: SkillManifest,
    source_url: str,
) -> str:
    """Determine the canonical skill name.

    WHY priority order: caller-supplied ``skill_name`` is authoritative when
    set, then the frontmatter's name, then a basename fallback. The stream id
    includes the name, so this must be resolved BEFORE the stream id is
    computed.
    """
    frontmatter_name = _name_from_frontmatter(frontmatter)
    default_name = explicit_name if explicit_name else frontmatter_name
    return default_name or _basename_from_url(source_url)


def _compute_tree_sha(files: list[SkillFile]) -> str:
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


def _extract_skill_frontmatter(
    files: list[SkillFile],
    source_url: str,
    version: str,
) -> SkillManifest:
    """Parse the YAML frontmatter of the tree's root SKILL.md.

    A skill tree is one skill folder; SKILL.md MUST sit at the tree root.
    Frontmatter MUST declare a non-empty ``name`` (lowercase, hyphens) and
    ``description``, per the vercel-labs/skills convention.
    """
    manifest_file = next((f for f in files if f.rel_path == _MANIFEST_PATH), None)
    if manifest_file is None:
        raise SkillManifestMissing(source_url, version)
    try:
        text = manifest_file.content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SkillManifestInvalid(source_url, version, str(exc)) from exc
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise SkillManifestInvalid(source_url, version, "SKILL.md has no YAML frontmatter block")
    try:
        parsed = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise SkillManifestInvalid(source_url, version, str(exc)) from exc
    if not isinstance(parsed, dict):
        raise SkillManifestInvalid(source_url, version, "frontmatter must be a YAML mapping")
    frontmatter = {str(k): v for k, v in parsed.items() if isinstance(k, str)}
    name = frontmatter.get("name")
    if not isinstance(name, str) or not name.strip():
        raise SkillManifestInvalid(source_url, version, "frontmatter must declare 'name'")
    return frontmatter


def _name_from_frontmatter(frontmatter: SkillManifest) -> str:
    """Return ``frontmatter['name']`` as a clean string, or empty if missing."""
    name_value = frontmatter.get("name")
    if isinstance(name_value, str) and name_value.strip():
        return name_value.strip()
    return ""


def _basename_from_url(source_url: str) -> str:
    """Last path segment of the source URL (minus a ``.git`` suffix).

    Used as the final fallback display name when neither the request body nor
    the frontmatter provided one. Mirrors the CLI's ``SkillRef`` default so
    the lock entry's display name is stable regardless of which side picked
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
    aggregate: SkillRegistrationAggregate,
) -> RegisterSkillResult:
    if (
        aggregate.source_url is None
        or aggregate.skill_version is None
        or aggregate.resolved_sha is None
        or aggregate.skill_name is None
        or aggregate.tree_storage_prefix is None
    ):
        msg = (
            "SkillRegistrationAggregate is missing required fields - "
            "aggregate replay produced an empty state"
        )
        raise RuntimeError(msg)
    return RegisterSkillResult(
        skill_name=aggregate.skill_name,
        source_url=aggregate.source_url,
        version=aggregate.skill_version,
        resolved_sha=aggregate.resolved_sha,
        tree_storage_prefix=aggregate.tree_storage_prefix,
    )
