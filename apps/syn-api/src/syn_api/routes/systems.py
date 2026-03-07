"""System management API endpoints — thin wrapper over v1."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

import syn_api.v1.systems as sys_ops
from syn_api.types import Err, SystemErrorCode

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/systems", tags=["systems"])


@router.post("")
async def create_system(body: dict[str, Any]) -> dict[str, Any]:
    """Create a new system."""
    try:
        result = await sys_ops.create_system(
            organization_id=body["organization_id"],
            name=body["name"],
            description=body.get("description", ""),
            created_by=body.get("created_by", "api"),
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if isinstance(result, Err):
        raise HTTPException(status_code=400, detail=result.message)

    return {"system_id": result.value, "name": body["name"]}


@router.get("")
async def list_systems(organization_id: str | None = None) -> dict[str, Any]:
    """List systems with optional organization filter."""
    result = await sys_ops.list_systems(organization_id=organization_id)

    if isinstance(result, Err):
        raise HTTPException(status_code=500, detail=result.message)

    return {
        "systems": [s.model_dump() for s in result.value],
        "total": len(result.value),
    }


@router.get("/{system_id}")
async def get_system(system_id: str) -> dict[str, Any]:
    """Get system details."""
    result = await sys_ops.get_system(system_id)

    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=result.message)

    return result.value.model_dump()


@router.put("/{system_id}")
async def update_system(system_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Update a system."""
    result = await sys_ops.update_system(
        system_id=system_id,
        name=body.get("name"),
        description=body.get("description"),
    )

    if isinstance(result, Err):
        status = 404 if result.error == SystemErrorCode.NOT_FOUND else 400
        raise HTTPException(status_code=status, detail=result.message)

    return {"system_id": system_id, "status": "updated"}


@router.delete("/{system_id}")
async def delete_system(system_id: str) -> dict[str, Any]:
    """Soft-delete a system."""
    result = await sys_ops.delete_system(
        system_id=system_id,
        deleted_by="api",
    )

    if isinstance(result, Err):
        status = 404 if result.error == SystemErrorCode.NOT_FOUND else 409
        raise HTTPException(status_code=status, detail=result.message)

    return {"system_id": system_id, "status": "deleted"}
