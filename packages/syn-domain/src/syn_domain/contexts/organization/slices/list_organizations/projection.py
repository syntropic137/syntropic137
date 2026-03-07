"""Organization projection — re-exports from _shared for backward compat."""

from syn_domain.contexts.organization._shared.organization_projection import (
    OrganizationProjection,
    get_organization_projection,
    reset_organization_projection,
)

__all__ = [
    "OrganizationProjection",
    "get_organization_projection",
    "reset_organization_projection",
]
