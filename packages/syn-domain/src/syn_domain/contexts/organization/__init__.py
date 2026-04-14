"""Organization bounded context - organizations, systems, and repos.

Public API for cross-context consumers. Import from here, not from internal
subpackages (slices/, domain/aggregate_*/, etc.).

Usage:
    from syn_domain.contexts.organization import (
        OrganizationAggregate,
        SystemAggregate,
        RepoAggregate,
    )
"""

from syn_domain.contexts.organization.domain import HandlerResult
from syn_domain.contexts.organization.domain.aggregate_organization import (
    OrganizationAggregate,
)
from syn_domain.contexts.organization.domain.aggregate_repo import RepoAggregate
from syn_domain.contexts.organization.domain.aggregate_repo_claim import (
    RepoClaimAggregate,
)
from syn_domain.contexts.organization.domain.aggregate_system import SystemAggregate

__all__ = [
    "HandlerResult",
    "OrganizationAggregate",
    "RepoAggregate",
    "RepoClaimAggregate",
    "SystemAggregate",
]
