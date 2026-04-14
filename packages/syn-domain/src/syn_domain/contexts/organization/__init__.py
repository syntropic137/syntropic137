"""Organization bounded context - organizations, systems, and repos.

Public API for cross-context consumers. Import from here, not from internal
subpackages (slices/, domain/aggregate_*/, etc.).

Usage:
    from syn_domain.contexts.organization import (
        OrganizationAggregate,
        SystemAggregate,
        RepoAggregate,
        CreateOrganizationCommand,
        CreateOrganizationHandler,
    )
"""

# Aggregates
from syn_domain.contexts.organization.domain import HandlerResult
from syn_domain.contexts.organization.domain.aggregate_organization import (
    OrganizationAggregate,
)
from syn_domain.contexts.organization.domain.aggregate_repo import RepoAggregate
from syn_domain.contexts.organization.domain.aggregate_repo_claim import (
    RepoClaimAggregate,
)
from syn_domain.contexts.organization.domain.aggregate_repo_claim.claim_id import (
    compute_repo_claim_id,
)
from syn_domain.contexts.organization.domain.aggregate_system import SystemAggregate

# Commands
from syn_domain.contexts.organization.domain.commands.AssignRepoToSystemCommand import (
    AssignRepoToSystemCommand,
)
from syn_domain.contexts.organization.domain.commands.ClaimRepoCommand import (
    ClaimRepoCommand,
)
from syn_domain.contexts.organization.domain.commands.CreateOrganizationCommand import (
    CreateOrganizationCommand,
)
from syn_domain.contexts.organization.domain.commands.CreateSystemCommand import (
    CreateSystemCommand,
)
from syn_domain.contexts.organization.domain.commands.DeleteOrganizationCommand import (
    DeleteOrganizationCommand,
)
from syn_domain.contexts.organization.domain.commands.DeleteSystemCommand import (
    DeleteSystemCommand,
)
from syn_domain.contexts.organization.domain.commands.DeregisterRepoCommand import (
    DeregisterRepoCommand,
)
from syn_domain.contexts.organization.domain.commands.RegisterRepoCommand import (
    RegisterRepoCommand,
)
from syn_domain.contexts.organization.domain.commands.ReleaseRepoClaimCommand import (
    ReleaseRepoClaimCommand,
)
from syn_domain.contexts.organization.domain.commands.UnassignRepoFromSystemCommand import (
    UnassignRepoFromSystemCommand,
)
from syn_domain.contexts.organization.domain.commands.UpdateOrganizationCommand import (
    UpdateOrganizationCommand,
)
from syn_domain.contexts.organization.domain.commands.UpdateRepoCommand import (
    UpdateRepoCommand,
)
from syn_domain.contexts.organization.domain.commands.UpdateSystemCommand import (
    UpdateSystemCommand,
)

# Query types
from syn_domain.contexts.organization.domain.queries.get_contribution_heatmap import (
    GetContributionHeatmapQuery,
)
from syn_domain.contexts.organization.domain.queries.get_global_overview import (
    GetGlobalOverviewQuery,
)
from syn_domain.contexts.organization.domain.queries.get_repo_activity import (
    GetRepoActivityQuery,
)
from syn_domain.contexts.organization.domain.queries.get_repo_cost import (
    GetRepoCostQuery,
)
from syn_domain.contexts.organization.domain.queries.get_repo_failures import (
    GetRepoFailuresQuery,
)
from syn_domain.contexts.organization.domain.queries.get_repo_health import (
    GetRepoHealthQuery,
)
from syn_domain.contexts.organization.domain.queries.get_repo_sessions import (
    GetRepoSessionsQuery,
)
from syn_domain.contexts.organization.domain.queries.get_system_activity import (
    GetSystemActivityQuery,
)
from syn_domain.contexts.organization.domain.queries.get_system_cost import (
    GetSystemCostQuery,
)
from syn_domain.contexts.organization.domain.queries.get_system_history import (
    GetSystemHistoryQuery,
)
from syn_domain.contexts.organization.domain.queries.get_system_patterns import (
    GetSystemPatternsQuery,
)
from syn_domain.contexts.organization.domain.queries.get_system_status import (
    GetSystemStatusQuery,
)

# Command handlers
from syn_domain.contexts.organization.slices.create_organization.CreateOrganizationHandler import (
    CreateOrganizationHandler,
)
from syn_domain.contexts.organization.slices.create_system.CreateSystemHandler import (
    CreateSystemHandler,
)
from syn_domain.contexts.organization.slices.manage_organization.ManageOrganizationHandler import (
    ManageOrganizationHandler,
)
from syn_domain.contexts.organization.slices.manage_repo.ManageRepoHandler import (
    ManageRepoHandler,
)
from syn_domain.contexts.organization.slices.manage_system.ManageSystemHandler import (
    ManageSystemHandler,
)
from syn_domain.contexts.organization.slices.register_repo.RegisterRepoHandler import (
    RegisterRepoHandler,
)

# Query handlers
from syn_domain.contexts.organization.slices.contribution_heatmap.GetContributionHeatmapHandler import (
    GetContributionHeatmapHandler,
)
from syn_domain.contexts.organization.slices.global_overview.GetGlobalOverviewHandler import (
    GetGlobalOverviewHandler,
)
from syn_domain.contexts.organization.slices.repo_activity.GetRepoActivityHandler import (
    GetRepoActivityHandler,
)
from syn_domain.contexts.organization.slices.repo_cost.GetRepoCostHandler import (
    GetRepoCostHandler,
)
from syn_domain.contexts.organization.slices.repo_failures.GetRepoFailuresHandler import (
    GetRepoFailuresHandler,
)
from syn_domain.contexts.organization.slices.repo_health.GetRepoHealthHandler import (
    GetRepoHealthHandler,
)
from syn_domain.contexts.organization.slices.repo_sessions.GetRepoSessionsHandler import (
    GetRepoSessionsHandler,
)
from syn_domain.contexts.organization.slices.system_activity.GetSystemActivityHandler import (
    GetSystemActivityHandler,
)
from syn_domain.contexts.organization.slices.system_cost.GetSystemCostHandler import (
    GetSystemCostHandler,
)
from syn_domain.contexts.organization.slices.system_history.GetSystemHistoryHandler import (
    GetSystemHistoryHandler,
)
from syn_domain.contexts.organization.slices.system_patterns.GetSystemPatternsHandler import (
    GetSystemPatternsHandler,
)
from syn_domain.contexts.organization.slices.system_status.GetSystemStatusHandler import (
    GetSystemStatusHandler,
)

__all__ = [
    # Aggregates
    "HandlerResult",
    "OrganizationAggregate",
    "RepoAggregate",
    "RepoClaimAggregate",
    "SystemAggregate",
    # Utility
    "compute_repo_claim_id",
    # Commands
    "AssignRepoToSystemCommand",
    "ClaimRepoCommand",
    "CreateOrganizationCommand",
    "CreateSystemCommand",
    "DeleteOrganizationCommand",
    "DeleteSystemCommand",
    "DeregisterRepoCommand",
    "RegisterRepoCommand",
    "ReleaseRepoClaimCommand",
    "UnassignRepoFromSystemCommand",
    "UpdateOrganizationCommand",
    "UpdateRepoCommand",
    "UpdateSystemCommand",
    # Query types
    "GetContributionHeatmapQuery",
    "GetGlobalOverviewQuery",
    "GetRepoActivityQuery",
    "GetRepoCostQuery",
    "GetRepoFailuresQuery",
    "GetRepoHealthQuery",
    "GetRepoSessionsQuery",
    "GetSystemActivityQuery",
    "GetSystemCostQuery",
    "GetSystemHistoryQuery",
    "GetSystemPatternsQuery",
    "GetSystemStatusQuery",
    # Command handlers
    "CreateOrganizationHandler",
    "CreateSystemHandler",
    "ManageOrganizationHandler",
    "ManageRepoHandler",
    "ManageSystemHandler",
    "RegisterRepoHandler",
    # Query handlers
    "GetContributionHeatmapHandler",
    "GetGlobalOverviewHandler",
    "GetRepoActivityHandler",
    "GetRepoCostHandler",
    "GetRepoFailuresHandler",
    "GetRepoHealthHandler",
    "GetRepoSessionsHandler",
    "GetSystemActivityHandler",
    "GetSystemCostHandler",
    "GetSystemHistoryHandler",
    "GetSystemPatternsHandler",
    "GetSystemStatusHandler",
]
