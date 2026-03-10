"""Repo management API endpoints — thin wrapper over v1."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

import syn_api.v1.repos as repo_ops
from syn_api.types import Err, RepoError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/repos", tags=["repos"])


@router.post("")
async def register_repo(body: dict[str, Any]) -> dict[str, Any]:
    """Register a new repo."""
    try:
        result = await repo_ops.register_repo(
            organization_id=body["organization_id"],
            provider=body.get("provider", "github"),
            full_name=body["full_name"],
            owner=body.get("owner", ""),
            default_branch=body.get("default_branch", "main"),
            provider_repo_id=body.get("provider_repo_id", ""),
            installation_id=body.get("installation_id", ""),
            is_private=body.get("is_private", False),
            created_by=body.get("created_by", "api"),
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if isinstance(result, Err):
        raise HTTPException(status_code=400, detail=result.message)

    return {"repo_id": result.value, "full_name": body["full_name"]}


@router.get("")
async def list_repos(
    organization_id: str | None = None,
    system_id: str | None = None,
    provider: str | None = None,
    unassigned: bool = False,
) -> dict[str, Any]:
    """List repos with optional filters."""
    result = await repo_ops.list_repos(
        organization_id=organization_id,
        system_id=system_id,
        provider=provider,
        unassigned=unassigned,
    )

    if isinstance(result, Err):
        raise HTTPException(status_code=500, detail=result.message)

    return {
        "repos": [r.model_dump() for r in result.value],
        "total": len(result.value),
    }


@router.get("/{repo_id}")
async def get_repo(repo_id: str) -> dict[str, Any]:
    """Get repo details."""
    result = await repo_ops.get_repo(repo_id)

    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=result.message)

    return result.value.model_dump()


@router.post("/{repo_id}/assign")
async def assign_repo_to_system(repo_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Assign a repo to a system."""
    try:
        result = await repo_ops.assign_repo_to_system(
            repo_id=repo_id,
            system_id=body["system_id"],
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if isinstance(result, Err):
        status = 404 if result.error == RepoError.NOT_FOUND else 409
        raise HTTPException(status_code=status, detail=result.message)

    return {"repo_id": repo_id, "system_id": body["system_id"], "status": "assigned"}


@router.post("/{repo_id}/unassign")
async def unassign_repo_from_system(repo_id: str) -> dict[str, Any]:
    """Unassign a repo from its system."""
    result = await repo_ops.unassign_repo_from_system(repo_id=repo_id)

    if isinstance(result, Err):
        status = 404 if result.error == RepoError.NOT_FOUND else 409
        raise HTTPException(status_code=status, detail=result.message)

    return {"repo_id": repo_id, "status": "unassigned"}


# ---------------------------------------------------------------------------
# Insight endpoints
# ---------------------------------------------------------------------------


@router.get("/{repo_id}/health")
async def get_repo_health(repo_id: str) -> dict[str, Any]:
    """Get health snapshot for a repo."""
    result = await repo_ops.get_repo_health(repo_id)
    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=result.message)
    return result.value


@router.get("/{repo_id}/cost")
async def get_repo_cost(repo_id: str) -> dict[str, Any]:
    """Get cost breakdown for a repo."""
    result = await repo_ops.get_repo_cost(repo_id)
    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=result.message)
    return result.value


@router.get("/{repo_id}/activity")
async def get_repo_activity(repo_id: str, offset: int = 0, limit: int = 50) -> dict[str, Any]:
    """Get execution timeline for a repo."""
    result = await repo_ops.get_repo_activity(repo_id, offset=offset, limit=limit)
    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=result.message)
    entries = result.value
    return {"entries": entries, "total": len(entries)}


@router.get("/{repo_id}/failures")
async def get_repo_failures(repo_id: str, limit: int = 50) -> dict[str, Any]:
    """Get recent failures for a repo."""
    result = await repo_ops.get_repo_failures(repo_id, limit=limit)
    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=result.message)
    entries = result.value
    return {"failures": entries, "total": len(entries)}


@router.get("/{repo_id}/sessions")
async def get_repo_sessions(repo_id: str, limit: int = 50) -> dict[str, Any]:
    """Get agent sessions for a repo."""
    result = await repo_ops.get_repo_sessions(repo_id, limit=limit)
    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=result.message)
    sessions = result.value
    return {"sessions": sessions, "total": len(sessions)}
