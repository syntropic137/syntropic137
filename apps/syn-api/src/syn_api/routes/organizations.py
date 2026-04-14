"""Organization management API endpoints and service operations.

Provides CRUD for organizations with domain aggregate interaction.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from syn_api._wiring import (
    ensure_connected,
    sync_published_events_to_projections,
)
from syn_api.types import (
    CreateOrganizationRequest,
    Err,
    Ok,
    OrganizationActionResponse,
    OrganizationError,
    OrganizationListResponse,
    OrganizationSummaryResponse,
    Result,
    UpdateOrganizationRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/organizations", tags=["organizations"])


# =============================================================================
# Service functions (importable by tests)
# =============================================================================


async def create_organization(
    name: str,
    slug: str,
    created_by: str = "",
) -> Result[str, OrganizationError]:
    """Create a new organization."""
    from syn_adapters.storage.repositories import get_organization_repository
    from syn_domain.contexts.organization import CreateOrganizationCommand, CreateOrganizationHandler

    await ensure_connected()

    try:
        command = CreateOrganizationCommand(
            name=name,
            slug=slug,
            created_by=created_by,
        )
    except ValueError as e:
        return Err(OrganizationError.INVALID_INPUT, message=str(e))

    repo = get_organization_repository()
    handler = CreateOrganizationHandler(repository=repo)

    try:
        aggregate = await handler.handle(command)
        await sync_published_events_to_projections()
        return Ok(aggregate.organization_id)
    except Exception as e:
        return Err(OrganizationError.INVALID_INPUT, message=str(e))


async def list_organizations() -> Result[list[OrganizationSummaryResponse], OrganizationError]:
    """List all organizations."""
    from syn_domain.contexts.organization.slices.list_organizations.projection import (
        get_organization_projection,
    )

    await ensure_connected()

    projection = get_organization_projection()
    orgs = await projection.list_all()

    return Ok(
        [
            OrganizationSummaryResponse(
                organization_id=o.organization_id,
                name=o.name,
                slug=o.slug,
                created_by=o.created_by,
                created_at=o.created_at,
                system_count=o.system_count,
                repo_count=o.repo_count,
            )
            for o in orgs
        ]
    )


async def get_organization(
    organization_id: str,
) -> Result[OrganizationSummaryResponse, OrganizationError]:
    """Get organization details."""
    from syn_domain.contexts.organization.slices.list_organizations.projection import (
        get_organization_projection,
    )

    await ensure_connected()

    projection = get_organization_projection()
    org = await projection.get(organization_id)

    if org is None:
        return Err(OrganizationError.NOT_FOUND, message=f"Organization {organization_id} not found")

    return Ok(
        OrganizationSummaryResponse(
            organization_id=org.organization_id,
            name=org.name,
            slug=org.slug,
            created_by=org.created_by,
            created_at=org.created_at,
            system_count=org.system_count,
            repo_count=org.repo_count,
        )
    )


async def update_organization(
    organization_id: str,
    name: str | None = None,
    slug: str | None = None,
) -> Result[None, OrganizationError]:
    """Update an organization."""
    from syn_adapters.storage.repositories import get_organization_repository
    from syn_domain.contexts.organization import ManageOrganizationHandler, UpdateOrganizationCommand

    await ensure_connected()

    try:
        command = UpdateOrganizationCommand(
            organization_id=organization_id,
            name=name,
            slug=slug,
        )
    except ValueError as e:
        return Err(OrganizationError.INVALID_INPUT, message=str(e))

    repo = get_organization_repository()
    handler = ManageOrganizationHandler(repository=repo)
    result = await handler.update(command)

    if result is None:
        return Err(OrganizationError.NOT_FOUND, message=f"Organization {organization_id} not found")

    if not result.success:
        error_enum = _classify_org_error(result.error)
        return Err(error_enum, message=result.error)

    await sync_published_events_to_projections()
    return Ok(None)


async def delete_organization(
    organization_id: str,
    deleted_by: str = "",
) -> Result[None, OrganizationError]:
    """Soft-delete an organization."""
    from syn_adapters.storage.repositories import get_organization_repository
    from syn_domain.contexts.organization import DeleteOrganizationCommand, ManageOrganizationHandler

    await ensure_connected()

    try:
        command = DeleteOrganizationCommand(
            organization_id=organization_id,
            deleted_by=deleted_by,
        )
    except ValueError as e:
        return Err(OrganizationError.INVALID_INPUT, message=str(e))

    repo = get_organization_repository()
    handler = ManageOrganizationHandler(repository=repo)
    result = await handler.delete(command)

    if result is None:
        return Err(
            OrganizationError.NOT_FOUND,
            message=f"Organization {organization_id} not found",
        )

    if not result.success:
        error_enum = _classify_org_error(result.error)
        return Err(error_enum, message=result.error)

    await sync_published_events_to_projections()
    return Ok(None)


def _classify_org_error(error_msg: str) -> OrganizationError:
    """Map a domain ValueError message to a specific OrganizationError."""
    lower = error_msg.lower()
    if "already deleted" in lower:
        return OrganizationError.ALREADY_DELETED
    if "has systems" in lower:
        return OrganizationError.HAS_SYSTEMS
    if "has repos" in lower:
        return OrganizationError.HAS_REPOS
    return OrganizationError.INVALID_INPUT


# =============================================================================
# HTTP Endpoints
# =============================================================================


@router.post("", response_model=OrganizationActionResponse)
async def create_organization_endpoint(
    body: CreateOrganizationRequest,
) -> OrganizationActionResponse:
    """Create a new organization."""
    try:
        result = await create_organization(
            name=body.name,
            slug=body.slug,
            created_by=body.created_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if isinstance(result, Err):
        raise HTTPException(status_code=400, detail=result.message)

    return OrganizationActionResponse(
        organization_id=result.value,
        name=body.name,
        slug=body.slug,
        status="created",
    )


@router.get("", response_model=OrganizationListResponse)
async def list_organizations_endpoint() -> OrganizationListResponse:
    """List all organizations."""
    result = await list_organizations()

    if isinstance(result, Err):
        raise HTTPException(status_code=500, detail=result.message)

    return OrganizationListResponse(
        organizations=result.value,
        total=len(result.value),
    )


@router.get("/{organization_id}", response_model=OrganizationSummaryResponse)
async def get_organization_endpoint(organization_id: str) -> OrganizationSummaryResponse:
    """Get organization details."""
    from syn_api._wiring import get_projection_mgr
    from syn_api.prefix_resolver import resolve_or_raise

    mgr = get_projection_mgr()
    organization_id = await resolve_or_raise(
        mgr.store, "organizations", organization_id, "Organization"
    )
    result = await get_organization(organization_id)

    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=result.message)

    return result.value


@router.put(
    "/{organization_id}",
    response_model=OrganizationActionResponse,
    response_model_exclude_none=True,
)
async def update_organization_endpoint(
    organization_id: str, body: UpdateOrganizationRequest
) -> OrganizationActionResponse:
    """Update an organization."""
    result = await update_organization(
        organization_id=organization_id,
        name=body.name,
        slug=body.slug,
    )

    if isinstance(result, Err):
        status = 404 if result.error == OrganizationError.NOT_FOUND else 400
        raise HTTPException(status_code=status, detail=result.message)

    return OrganizationActionResponse(organization_id=organization_id, status="updated")


@router.delete(
    "/{organization_id}",
    response_model=OrganizationActionResponse,
    response_model_exclude_none=True,
)
async def delete_organization_endpoint(organization_id: str) -> OrganizationActionResponse:
    """Soft-delete an organization."""
    result = await delete_organization(
        organization_id=organization_id,
        deleted_by="api",
    )

    if isinstance(result, Err):
        status = 404 if result.error == OrganizationError.NOT_FOUND else 409
        raise HTTPException(status_code=status, detail=result.message)

    return OrganizationActionResponse(organization_id=organization_id, status="deleted")
