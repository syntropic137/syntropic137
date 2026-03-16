"""List Organizations query handler."""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.organization.slices.list_organizations.projection import (
    get_organization_projection,
)

if TYPE_CHECKING:
    from syn_domain.contexts.organization.domain.queries.list_organizations import (
        ListOrganizationsQuery,
    )
    from syn_domain.contexts.organization.domain.read_models.organization_summary import (
        OrganizationSummary,
    )


class ListOrganizationsHandler:
    def handle(self, query: ListOrganizationsQuery) -> list[OrganizationSummary]:  # noqa: ARG002
        projection = get_organization_projection()
        return projection.list_all()


_handler: ListOrganizationsHandler | None = None


def get_list_organizations_handler() -> ListOrganizationsHandler:
    global _handler
    if _handler is None:
        _handler = ListOrganizationsHandler()
    return _handler


def reset_list_organizations_handler() -> None:
    global _handler
    _handler = None
