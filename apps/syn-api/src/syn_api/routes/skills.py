# See ADR-066: this route module runs in syn-api and dispatches commands or
# reads projections; it does NO git or subprocess work. The CLI performs the
# git clone locally and POSTs the tree contents inline (issue #772).
"""Skill REST endpoints (issue #772).

Endpoints under ``/skills``:

- ``POST /skills/registrations`` - register a new (source, version, name) by
                                    uploading the tree contents.
- ``GET /skills/registrations``  - report whether a (source, version, name)
                                    triple is already registered, so a caller
                                    can skip uploading a tree that is stored.
- ``GET /skills/storage``        - size of the content-addressed skill store.
- ``GET /skills``                - list every registered skill.
- ``GET /skills/{skill_name}``   - every registration sharing that name.

Route order matters: ``/{skill_name}`` is declared last so it cannot shadow
the literal paths above it.

Mirrors ``routes/claude_plugins.py``. Typed ``SkillError`` subclasses raised
by the handler map to HTTP 422 via ``skill_error_mapping`` so callers see
stable ``error_code`` strings.
"""

from __future__ import annotations

import base64
import binascii
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query

from syn_api._wiring import (
    ensure_connected,
    get_register_skill_handler,
    get_skill_lock_projection,
    sync_published_events_to_projections,
)
from syn_api.services.skill_error_mapping import http_exception_for_skill_error
from syn_api.types import (
    RegisterSkillRequest,
    SkillDetailResponse,
    SkillFilePayload,
    SkillListResponse,
    SkillRegistrationLookupResponse,
    SkillRegistrationResponse,
    SkillRegistrationSummary,
    SkillStorageStatsResponse,
)
from syn_domain.contexts.orchestration import SkillError
from syn_domain.contexts.orchestration.ports.SkillStoragePort import SkillFile

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.slices.register_skill.projection import (
        SkillLockEntry,
    )

router = APIRouter(prefix="/skills", tags=["skills"])

# WHY (mirrors issue #726 review): the CLI enforces this cap client-side, but
# direct API clients bypass that. Mirror the cap server-side so a hostile or
# buggy client cannot make the API accumulate arbitrarily large decoded trees.
MAX_SKILL_TREE_BYTES = 50 * 1024 * 1024

# WHY: a generous ceiling on file count; real skill trees are a few dozen
# files at most. Checked before any base64 decoding happens.
MAX_SKILL_TREE_FILES = 10_000

# Short form of a content hash for narrow table columns. Formatting lives in
# the API so every client renders it identically (see feedback on display
# fields belonging server-side).
_SHA_DISPLAY_CHARS = 12


def _decode_files(entries: list[SkillFilePayload]) -> list[SkillFile]:
    """Decode the base64-encoded request files into domain value objects.

    Bad base64 surfaces as a 400 (caller-controlled input shape) rather than
    a 500. Over-limit trees surface as 413: the file count is checked before
    any decoding, and the cumulative decoded size is estimated from the
    base64 length (4 chars encode 3 bytes) BEFORE each decode so a hostile
    payload is rejected without materializing the decoded bytes.
    """
    if len(entries) > MAX_SKILL_TREE_FILES:
        raise HTTPException(
            status_code=413,
            detail=(f"Skill tree has {len(entries)} files; the limit is {MAX_SKILL_TREE_FILES}"),
        )
    decoded: list[SkillFile] = []
    total_bytes = 0
    for raw in entries:
        estimated = (len(raw.content_base64) * 3) // 4
        if total_bytes + estimated > MAX_SKILL_TREE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Skill tree exceeds {MAX_SKILL_TREE_BYTES} bytes "
                    f"({MAX_SKILL_TREE_BYTES // (1024 * 1024)} MiB); "
                    "refusing the registration"
                ),
            )
        try:
            content = base64.b64decode(raw.content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid base64 content for {raw.rel_path!r}: {exc}",
            ) from exc
        total_bytes += len(content)
        decoded.append(SkillFile(rel_path=raw.rel_path, content=content))
    return decoded


@router.get("", response_model=SkillListResponse)
async def list_skills() -> SkillListResponse:
    """List every registered skill (issue #826).

    Reads the ``skill_lock`` projection, the same read model run-time
    resolution uses, so what this reports is what a run would resolve.
    """
    await ensure_connected()
    entries = await get_skill_lock_projection().list_all()
    summaries = [_summary_from_entry(e) for e in entries]
    return SkillListResponse(skills=summaries, total=len(summaries))


@router.get("/storage", response_model=SkillStorageStatsResponse)
async def get_skill_storage_stats() -> SkillStorageStatsResponse:
    """Report how much space registered skill trees occupy.

    Eviction is deliberately not implemented, so size is made observable
    rather than assumed small.
    """
    from syn_api._wiring import get_skill_storage

    stats = await (await get_skill_storage()).stats()
    return SkillStorageStatsResponse(
        object_count=stats.object_count,
        total_bytes=stats.total_bytes,
        skill_count=stats.skill_count,
        truncated=stats.truncated,
    )


@router.get("/registrations", response_model=SkillRegistrationLookupResponse)
async def lookup_skill_registration(
    source_url: str = Query(..., description="Skill source repository URL"),
    version: str = Query(..., description="Pinned version (tag, branch, or commit)"),
    skill_name: str = Query(..., description="Skill name as declared or overridden"),
) -> SkillRegistrationLookupResponse:
    """Report whether this skill triple is already registered.

    WHY a read surface exists: the skills API had only a write endpoint, so a
    caller could not distinguish an already-stored skill from a new one without
    uploading the whole tree. The returned sha is the cache key.
    """
    await ensure_connected()
    entry = await get_skill_lock_projection().get(
        source_url=source_url, version=version, skill_name=skill_name
    )
    if entry is None:
        return SkillRegistrationLookupResponse(registered=False)
    return SkillRegistrationLookupResponse(registered=True, resolved_sha=entry.resolved_sha)


@router.post(
    "/registrations",
    response_model=SkillRegistrationResponse,
    status_code=201,
    responses={
        400: {"description": "Malformed file payload (bad base64, missing fields)"},
        413: {"description": "Skill tree exceeds the size or file-count limit"},
        422: {"description": "Manifest missing, malformed, or unsafe file path in the tree"},
    },
)
async def register_skill_endpoint(
    body: RegisterSkillRequest,
) -> SkillRegistrationResponse:
    """Register a skill by uploading the cloned tree (issue #772).

    The CLI clones the source locally and POSTs the tree contents here. The
    API decodes the base64 file contents, computes the sha256 over the
    normalized tree, uploads to storage, and dispatches a
    ``RegisterSkillCommand`` against the existing aggregate. Idempotent on
    re-submission of the same ``(source_url, version, skill_name)``.
    """
    files = _decode_files(body.files)
    await ensure_connected()
    handler = await get_register_skill_handler()
    try:
        result = await handler.handle(
            source_url=body.source_url,
            version=body.version,
            skill_name=body.skill_name,
            files=files,
        )
    except SkillError as exc:
        raise http_exception_for_skill_error(exc) from exc
    await sync_published_events_to_projections()
    return SkillRegistrationResponse(
        skill_name=result.skill_name,
        source_url=result.source_url,
        version=result.version,
        resolved_sha=result.resolved_sha,
        tree_storage_prefix=result.tree_storage_prefix,
    )


def _summary_from_entry(entry: SkillLockEntry) -> SkillRegistrationSummary:
    return SkillRegistrationSummary(
        skill_name=entry.skill_name,
        source_url=entry.source_url,
        version=entry.version,
        resolved_sha=entry.resolved_sha,
        resolved_sha_display=entry.resolved_sha[:_SHA_DISPLAY_CHARS],
        tree_storage_prefix=entry.tree_storage_prefix,
        registered_at=entry.registered_at,
    )


# WHY this route is declared LAST: FastAPI matches in declaration order, so a
# path parameter registered before "/storage" and "/registrations" would
# swallow them. Keep any new literal /skills/... route above this one.
@router.get(
    "/{skill_name}",
    response_model=SkillDetailResponse,
    responses={404: {"description": "No skill registered under that name"}},
)
async def get_skill_detail(skill_name: str) -> SkillDetailResponse:
    """Every registration sharing a skill name (issue #826).

    A name is not unique - the same skill can be pinned at several versions,
    and two sources can publish the same name - so all matches are returned
    rather than an arbitrary one.
    """
    await ensure_connected()
    entries = [
        e for e in await get_skill_lock_projection().list_all() if e.skill_name == skill_name
    ]
    if not entries:
        raise HTTPException(
            status_code=404,
            detail=f"No skill registered under the name {skill_name!r}",
        )
    return SkillDetailResponse(
        skill_name=skill_name,
        registrations=[_summary_from_entry(e) for e in entries],
    )
