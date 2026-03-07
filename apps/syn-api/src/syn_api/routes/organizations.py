"""Organization management API endpoints — thin wrapper over v1."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

import syn_api.v1.organizations as orgs
from syn_api.types import Err, OrganizationError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.post("")
async def create_organization(body: dict[str, Any]) -> dict[str, Any]:
    """Create a new organization."""
    try:
        result = await orgs.create_organization(
            name=body["name"],
            slug=body["slug"],
            created_by=body.get("created_by", "api"),
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if isinstance(result, Err):
        raise HTTPException(status_code=400, detail=result.message)

    return {"organization_id": result.value, "name": body["name"], "slug": body["slug"]}


@router.get("")
async def list_organizations() -> dict[str, Any]:
    """List all organizations."""
    result = await orgs.list_organizations()

    if isinstance(result, Err):
        raise HTTPException(status_code=500, detail=result.message)

    return {
        "organizations": [o.model_dump() for o in result.value],
        "total": len(result.value),
    }


@router.get("/{organization_id}")
async def get_organization(organization_id: str) -> dict[str, Any]:
    """Get organization details."""
    result = await orgs.get_organization(organization_id)

    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=result.message)

    return result.value.model_dump()


@router.put("/{organization_id}")
async def update_organization(organization_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Update an organization."""
    result = await orgs.update_organization(
        organization_id=organization_id,
        name=body.get("name"),
        slug=body.get("slug"),
    )

    if isinstance(result, Err):
        status = 404 if result.error == OrganizationError.NOT_FOUND else 400
        raise HTTPException(status_code=status, detail=result.message)

    return {"organization_id": organization_id, "status": "updated"}


@router.delete("/{organization_id}")
async def delete_organization(organization_id: str) -> dict[str, Any]:
    """Soft-delete an organization."""
    result = await orgs.delete_organization(
        organization_id=organization_id,
        deleted_by="api",
    )

    if isinstance(result, Err):
        status = 404 if result.error == OrganizationError.NOT_FOUND else 409
        raise HTTPException(status_code=status, detail=result.message)

    return {"organization_id": organization_id, "status": "deleted"}
