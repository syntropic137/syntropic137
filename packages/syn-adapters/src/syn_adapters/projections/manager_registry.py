"""Projection registry — factory functions for creating projection instances.

Extracted from manager.py to reduce module complexity.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from syn_adapters.projections.session_tools import SessionToolsProjection
from syn_domain.contexts.agent_sessions.slices.list_sessions import SessionListProjection
from syn_domain.contexts.agent_sessions.slices.session_cost.projection import SessionCostProjection
from syn_domain.contexts.agent_sessions.slices.tool_timeline import ToolTimelineProjection
from syn_domain.contexts.artifacts.slices.list_artifacts import ArtifactListProjection
from syn_domain.contexts.orchestration.slices.dashboard_metrics import DashboardMetricsProjection
from syn_domain.contexts.orchestration.slices.execution_cost.projection import (
    ExecutionCostProjection,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail import (
    WorkflowExecutionDetailProjection,
)
from syn_domain.contexts.orchestration.slices.get_workflow_detail import (
    WorkflowDetailProjection,
)
from syn_domain.contexts.orchestration.slices.list_executions import (
    WorkflowExecutionListProjection,
)
from syn_domain.contexts.orchestration.slices.list_workflows import WorkflowListProjection
from syn_domain.contexts.orchestration.slices.workflow_phase_metrics import (
    WorkflowPhaseMetricsProjection,
)
from syn_domain.contexts.organization._shared.organization_projection import (
    OrganizationProjection,
)
from syn_domain.contexts.organization.slices.list_repos.projection import RepoProjection
from syn_domain.contexts.organization.slices.list_systems.projection import SystemProjection
from syn_domain.contexts.organization.slices.repo_correlation import (
    RepoCorrelationProjection,
)
from syn_domain.contexts.organization.slices.repo_cost import RepoCostProjection
from syn_domain.contexts.organization.slices.repo_health import RepoHealthProjection

if TYPE_CHECKING:
    from syn_adapters.projection_stores import ProjectionStoreProtocol

logger = logging.getLogger(__name__)


def create_session_tools_projection() -> SessionToolsProjection:
    """Create SessionToolsProjection with TimescaleDB access.

    This projection queries TimescaleDB for tool operations.
    See ADR-029: Simplified Event System

    Note: We don't pass the pool here because the store may not be
    initialized yet. The projection will get the pool lazily.
    """
    return SessionToolsProjection(pool=None)


def create_session_cost_projection(store: ProjectionStoreProtocol) -> SessionCostProjection:
    """Create SessionCostProjection with TimescaleDB access.

    This projection now queries TimescaleDB directly for real-time cost calculation.
    See ADR-029: Simplified Event System
    """
    try:
        from syn_adapters.events import get_event_store

        event_store = get_event_store()
        return SessionCostProjection(store, pool=event_store.pool)
    except Exception as e:
        logger.warning(
            "Could not connect to TimescaleDB for cost projection, falling back to event store: %s",
            e,
        )
        return SessionCostProjection(store)


def _create_execution_cost_projection(store: ProjectionStoreProtocol) -> ExecutionCostProjection:
    """Create ExecutionCostProjection with TimescaleDB access.

    This projection now queries TimescaleDB directly for real-time cost calculation.
    See ADR-029: Simplified Event System
    """
    try:
        from syn_adapters.events import get_event_store

        event_store = get_event_store()
        return ExecutionCostProjection(store, pool=event_store.pool)
    except Exception as e:
        logger.warning(
            "Could not connect to TimescaleDB for execution cost projection, "
            "falling back to projection store: %s",
            e,
        )
        return ExecutionCostProjection(store)


def _create_repo_cost_projection(store: ProjectionStoreProtocol) -> RepoCostProjection:
    """Create RepoCostProjection with TimescaleDB access.

    This projection now queries TimescaleDB directly for real-time cost calculation.
    See ADR-029: Simplified Event System
    """
    try:
        from syn_adapters.events import get_event_store

        event_store = get_event_store()
        return RepoCostProjection(store, pool=event_store.pool)
    except Exception as e:
        logger.warning(
            "Could not connect to TimescaleDB for repo cost projection, "
            "falling back to projection store: %s",
            e,
        )
        return RepoCostProjection(store)


def build_projection_registry(store: ProjectionStoreProtocol) -> dict[str, Any]:
    """Build the full projection registry dictionary.

    Args:
        store: The projection store for store-backed projections.

    Returns:
        Dictionary mapping projection names to projection instances.
    """
    from syn_adapters.projections.realtime import get_realtime_projection

    return {
        "workflow_list": WorkflowListProjection(store),
        "workflow_detail": WorkflowDetailProjection(store),
        "workflow_execution_list": WorkflowExecutionListProjection(store),
        "workflow_execution_detail": WorkflowExecutionDetailProjection(store),
        "session_list": SessionListProjection(store),
        "artifact_list": ArtifactListProjection(store),
        "dashboard_metrics": DashboardMetricsProjection(store),
        "workflow_phase_metrics": WorkflowPhaseMetricsProjection(store),
        # Observability projections (Pattern 2: Event Log + CQRS)
        "tool_timeline": ToolTimelineProjection(store),
        # Cost tracking projections (now query TimescaleDB directly)
        "session_cost": create_session_cost_projection(store),
        "execution_cost": _create_execution_cost_projection(store),
        # TimescaleDB-backed observability projections (CQRS pattern)
        "session_tools": create_session_tools_projection(),
        # Organization context projections — list/show entities
        "organization_list": OrganizationProjection(store),
        "system_list": SystemProjection(store),
        "repo_list": RepoProjection(store),
        # Organization insight projections — cross-context correlation
        "repo_correlation": RepoCorrelationProjection(store),
        "repo_health": RepoHealthProjection(store),
        "repo_cost": _create_repo_cost_projection(store),
        # Processor to-do list (ISS-196) — store-backed for crash resilience (ISS-222)
        "execution_todo": ExecutionTodoProjection(store=store),
        # Real-time projection for SSE push (doesn't use store)
        "realtime": get_realtime_projection(),
    }
