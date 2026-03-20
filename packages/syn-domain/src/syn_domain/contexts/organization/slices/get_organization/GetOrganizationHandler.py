"""Get Organization query handler."""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.organization._shared.organization_projection import (
    get_organization_projection,
)

if TYPE_CHECKING:
    from syn_domain.contexts.organization.domain.queries.get_organization import (
        GetOrganizationQuery,
    )
    from syn_domain.contexts.organization.domain.read_models.organization_summary import (
        OrganizationSummary,
    )


class GetOrganizationHandler:
    async def handle(self, query: GetOrganizationQuery) -> OrganizationSummary | None:
        projection = get_organization_projection()
        return await projection.get(query.organization_id)


_handler: GetOrganizationHandler | None = None


def get_get_organization_handler() -> GetOrganizationHandler:
    global _handler
    if _handler is None:
        _handler = GetOrganizationHandler()
    return _handler


def reset_get_organization_handler() -> None:
    global _handler
    _handler = None
