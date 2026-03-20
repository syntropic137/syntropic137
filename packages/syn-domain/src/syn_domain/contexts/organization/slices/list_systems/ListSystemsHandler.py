"""List Systems query handler."""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.organization.slices.list_systems.projection import (
    get_system_projection,
)

if TYPE_CHECKING:
    from syn_domain.contexts.organization.domain.queries.list_systems import (
        ListSystemsQuery,
    )
    from syn_domain.contexts.organization.domain.read_models.system_summary import (
        SystemSummary,
    )


class ListSystemsHandler:
    async def handle(self, query: ListSystemsQuery) -> list[SystemSummary]:
        projection = get_system_projection()
        return await projection.list_all(organization_id=query.organization_id)


_handler: ListSystemsHandler | None = None


def get_list_systems_handler() -> ListSystemsHandler:
    global _handler
    if _handler is None:
        _handler = ListSystemsHandler()
    return _handler


def reset_list_systems_handler() -> None:
    global _handler
    _handler = None
