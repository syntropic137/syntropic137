# See ADR-066: this route module runs in syn-api and dispatches commands or
# reads projections; it does NO git or subprocess work. The CLI performs the
# git clone locally and POSTs the tree contents inline (#726 Phase A).
"""Claude plugin REST endpoints (issue #726, Phase A redesign).

Endpoints under ``/claude-plugins``:

- ``POST   /claude-plugins/registrations``   - register a new (source, version)
                                               by uploading the tree contents.
- ``POST   /claude-plugins/global``          - add an already-registered plugin
                                               to the global registry.
- ``DELETE /claude-plugins/global/{name}``   - remove a global plugin entry.
- ``GET    /claude-plugins/global``          - list global plugins.
- ``GET    /claude-plugins``                 - list every locked plugin.
- ``GET    /claude-plugins/{name}/{version}``- show one lock entry.

Typed ``ClaudePluginError`` subclasses raised by the handlers map to HTTP 422
via ``claude_plugin_error_mapping`` so callers see stable ``error_code`` strings.
``ClaudePluginNotRegistered`` maps to 404 (the lock entry the caller asked for
does not exist).
"""

from __future__ import annotations

import base64
import binascii
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException

from syn_api._wiring import (
    ensure_connected,
    get_add_global_claude_plugin_handler,
    get_global_claude_plugins_projection,
    get_list_claude_plugins_handler,
    get_list_global_claude_plugins_handler,
    get_register_claude_plugin_handler,
    get_remove_global_claude_plugin_handler,
    get_show_claude_plugin_handler,
    sync_published_events_to_projections,
)
from syn_api.services.claude_plugin_error_mapping import (
    http_exception_for_claude_plugin_error,
)
from syn_api.types import (
    AddGlobalClaudePluginRequest,
    ClaudePluginFileEntry,
    ClaudePluginLockListResponse,
    ClaudePluginLockResponse,
    GlobalClaudePluginListResponse,
    GlobalClaudePluginResponse,
    RegisterClaudePluginRequest,
    RegisterClaudePluginResponse,
    RemoveGlobalClaudePluginResponse,
)
from syn_domain.contexts.orchestration._shared.claude_plugin_errors import (
    ClaudePluginError,
    ClaudePluginNotRegistered,
)
from syn_domain.contexts.orchestration.ports.ClaudePluginStoragePort import (
    ClaudePluginFile,
)
from syn_domain.contexts.orchestration.slices.manage_global_claude_plugins import (
    GlobalClaudePluginEntry,
    GlobalClaudePluginNotFoundError,
)
from syn_domain.contexts.orchestration.slices.show_claude_plugin import (
    ClaudePluginNotFoundError,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.slices.register_claude_plugin.projection import (
        LockEntry,
    )

router = APIRouter(prefix="/claude-plugins", tags=["claude-plugins"])


def _to_global_response(entry: GlobalClaudePluginEntry) -> GlobalClaudePluginResponse:
    return GlobalClaudePluginResponse(
        name=entry.name,
        source_url=entry.source_url,
        version=entry.version,
        resolved_sha=entry.resolved_sha,
        added_at=entry.added_at,
    )


def _to_lock_response(entry: LockEntry) -> ClaudePluginLockResponse:
    return ClaudePluginLockResponse(
        name=entry.name,
        source_url=entry.source_url,
        version=entry.version,
        resolved_sha=entry.resolved_sha,
        tree_storage_prefix=entry.tree_storage_prefix,
        registered_at=entry.registered_at,
    )


def _decode_files(entries: list[ClaudePluginFileEntry]) -> list[ClaudePluginFile]:
    """Decode the base64-encoded request files into domain value objects.

    Bad base64 surfaces as a 400 (caller-controlled input shape) rather than a
    500.
    """
    decoded: list[ClaudePluginFile] = []
    for raw in entries:
        try:
            content = base64.b64decode(raw.content_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid base64 content for {raw.rel_path!r}: {exc}",
            ) from exc
        decoded.append(ClaudePluginFile(rel_path=raw.rel_path, content=content))
    return decoded


@router.post(
    "/registrations",
    response_model=RegisterClaudePluginResponse,
    status_code=201,
    responses={
        400: {"description": "Malformed file payload (bad base64, missing fields)"},
        422: {"description": "Manifest missing or malformed in the uploaded tree"},
    },
)
async def register_claude_plugin_endpoint(
    body: RegisterClaudePluginRequest,
) -> RegisterClaudePluginResponse:
    """Register a plugin by uploading the cloned tree (Phase A redesign).

    The CLI clones the source locally, parses the manifest, and POSTs the tree
    contents here. The API decodes the base64 file contents, computes the
    sha256 over the normalized tree, uploads to storage, and dispatches a
    ``RegisterClaudePluginCommand`` against the existing aggregate. Idempotent
    on re-submission of the same ``(source_url, version)``.
    """
    files = _decode_files(body.files)
    await ensure_connected()
    handler = await get_register_claude_plugin_handler()
    try:
        result = await handler.handle(
            source_url=body.source_url,
            version=body.version,
            name=body.name,
            manifest=body.manifest,
            files=files,
        )
    except ClaudePluginError as exc:
        raise http_exception_for_claude_plugin_error(exc) from exc
    await sync_published_events_to_projections()
    return RegisterClaudePluginResponse(
        name=result.name,
        version=result.version,
        sha256=result.resolved_sha,
    )


@router.post(
    "/global",
    response_model=GlobalClaudePluginResponse,
    status_code=201,
    responses={
        404: {"description": "Plugin not registered; register via /registrations first"},
    },
)
async def add_global_claude_plugin_endpoint(
    body: AddGlobalClaudePluginRequest,
) -> GlobalClaudePluginResponse:
    """Add an already-registered plugin to the global registry.

    Looks up ``(name, version)`` in the lock projection and dispatches the add
    command. Returns 404 with ``error_code=claude_plugin_not_registered`` if the
    plugin has not been registered yet.
    """
    await ensure_connected()
    handler = await get_add_global_claude_plugin_handler()
    try:
        result = await handler.handle(name=body.name, version=body.version)
    except ClaudePluginNotRegistered as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": exc.error_code,
                "message": str(exc),
                "name": exc.name,
                "version": exc.version,
            },
        ) from exc
    await sync_published_events_to_projections()
    # WHY: the canonical ``added_at`` lives on the projection (set when the
    # GlobalClaudePluginAddedEvent was applied). Read it after the sync so the
    # POST response matches what a subsequent GET /global will return.
    projection = get_global_claude_plugins_projection()
    entry = await projection.get_by_name(result.name)
    added_at = entry.added_at if entry is not None else None
    return GlobalClaudePluginResponse(
        name=result.name,
        source_url=result.source_url,
        version=result.version,
        resolved_sha=result.resolved_sha,
        added_at=added_at,
    )


@router.delete(
    "/global/{name}",
    response_model=RemoveGlobalClaudePluginResponse,
    responses={404: {"description": "Plugin not present in the global registry"}},
)
async def remove_global_claude_plugin_endpoint(
    name: str,
) -> RemoveGlobalClaudePluginResponse:
    """Remove a plugin from the global registry by display name.

    The underlying lock entry is left in place so any workflow that pinned the
    same ``(source_url, version)`` continues to resolve.
    """
    await ensure_connected()
    handler = get_remove_global_claude_plugin_handler()
    try:
        result = await handler.handle(name)
    except GlobalClaudePluginNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    # WHY (issue #726): the projection is updated by the subscription pipeline.
    # In the in-memory test wiring there is no subscription service, so we
    # bridge published events here. In production this is a no-op (the
    # publisher is the no-op variant) and the coordinator catches the event.
    # Without this bridge, GET /global immediately after DELETE could still
    # show the removed entry until the projection caught up.
    await sync_published_events_to_projections()
    return RemoveGlobalClaudePluginResponse(name=result.name, status="removed")


@router.get("/global", response_model=GlobalClaudePluginListResponse)
async def list_global_claude_plugins_endpoint() -> GlobalClaudePluginListResponse:
    """List currently-active global claude plugins (sorted by name)."""
    await ensure_connected()
    handler = get_list_global_claude_plugins_handler()
    entries = await handler.handle()
    plugins = [_to_global_response(e) for e in entries]
    return GlobalClaudePluginListResponse(plugins=plugins, total=len(plugins))


@router.get("", response_model=ClaudePluginLockListResponse)
async def list_claude_plugins_endpoint() -> ClaudePluginLockListResponse:
    """List every entry currently in the lock projection."""
    await ensure_connected()
    handler = get_list_claude_plugins_handler()
    entries = await handler.handle()
    plugins = [_to_lock_response(e) for e in entries]
    return ClaudePluginLockListResponse(plugins=plugins, total=len(plugins))


@router.get(
    "/{name}/{version}",
    response_model=ClaudePluginLockResponse,
    responses={404: {"description": "No lock entry for the given (name, version)"}},
)
async def show_claude_plugin_endpoint(name: str, version: str) -> ClaudePluginLockResponse:
    """Look up a single lock entry by display name and version."""
    await ensure_connected()
    handler = get_show_claude_plugin_handler()
    try:
        entry = await handler.handle(name, version)
    except ClaudePluginNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_lock_response(entry)
