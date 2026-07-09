# See ADR-066: this route module runs in syn-api and dispatches commands or
# reads projections; it does NO git or subprocess work. The CLI performs the
# git clone locally and POSTs the tree contents inline (issue #772).
"""Skill REST endpoints (issue #772).

Endpoints under ``/skills``:

- ``POST /skills/registrations`` - register a new (source, version, name) by
                                    uploading the tree contents.

Mirrors ``routes/claude_plugins.py``. Typed ``SkillError`` subclasses raised
by the handler map to HTTP 422 via ``skill_error_mapping`` so callers see
stable ``error_code`` strings.
"""

from __future__ import annotations

import base64
import binascii

from fastapi import APIRouter, HTTPException

from syn_api._wiring import (
    ensure_connected,
    get_register_skill_handler,
    sync_published_events_to_projections,
)
from syn_api.services.skill_error_mapping import http_exception_for_skill_error
from syn_api.types import RegisterSkillRequest, SkillFilePayload, SkillRegistrationResponse
from syn_domain.contexts.orchestration import SkillError
from syn_domain.contexts.orchestration.ports.SkillStoragePort import SkillFile

router = APIRouter(prefix="/skills", tags=["skills"])

# WHY (mirrors issue #726 review): the CLI enforces this cap client-side, but
# direct API clients bypass that. Mirror the cap server-side so a hostile or
# buggy client cannot make the API accumulate arbitrarily large decoded trees.
MAX_SKILL_TREE_BYTES = 50 * 1024 * 1024

# WHY: a generous ceiling on file count; real skill trees are a few dozen
# files at most. Checked before any base64 decoding happens.
MAX_SKILL_TREE_FILES = 10_000


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
