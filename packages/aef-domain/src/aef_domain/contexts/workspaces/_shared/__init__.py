"""Shared workspace domain models.

This module exports:
- Value objects (immutable config, status, results)
- Port interfaces (DI boundaries)
- WorkspaceAggregate (event-sourced aggregate root)
"""

from aef_domain.contexts.workspaces._shared.ports import (
    ArtifactCollectionPort,
    EventStreamPort,
    GitConfigurationPort,
    IsolationBackendPort,
    IsolationCreationError,
    IsolationDestroyError,
    IsolationExecutionError,
    SidecarPort,
    SidecarStartError,
    StreamExecutionError,
    TokenInjectionPort,
    TokenVendingError,
    TokenVendingPort,
    WorkspacePortError,
)
from aef_domain.contexts.workspaces._shared.value_objects import (
    Artifact,
    ArtifactCollectionResult,
    CapabilityType,
    ExecutionResult,
    InjectionMethod,
    IsolationBackendType,
    IsolationConfig,
    IsolationHandle,
    SecurityPolicy,
    SidecarConfig,
    SidecarHandle,
    TokenInjectionResult,
    TokenType,
    WorkspaceStatus,
)
from aef_domain.contexts.workspaces._shared.WorkspaceAggregate import WorkspaceAggregate

__all__ = [
    # Sorted alphabetically (ruff RUF022)
    "Artifact",
    "ArtifactCollectionPort",
    "ArtifactCollectionResult",
    "CapabilityType",
    "EventStreamPort",
    "ExecutionResult",
    "GitConfigurationPort",
    "InjectionMethod",
    "IsolationBackendPort",
    "IsolationBackendType",
    "IsolationConfig",
    "IsolationCreationError",
    "IsolationDestroyError",
    "IsolationExecutionError",
    "IsolationHandle",
    "SecurityPolicy",
    "SidecarConfig",
    "SidecarHandle",
    "SidecarPort",
    "SidecarStartError",
    "StreamExecutionError",
    "TokenInjectionPort",
    "TokenInjectionResult",
    "TokenType",
    "TokenVendingError",
    "TokenVendingPort",
    "WorkspaceAggregate",
    "WorkspacePortError",
    "WorkspaceStatus",
]
