"""Workspace lifecycle helpers for WorkspaceService.

Extracted from WorkspaceService.create_workspace() to reduce method complexity.
These are standalone functions that implement individual lifecycle steps.

See ADR-021, ADR-023, ADR-024.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationConfig,
    SecurityPolicy,
    SidecarConfig,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.WorkspaceAggregate import (
    WorkspaceAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.CreateWorkspaceCommand import (
    CreateWorkspaceCommand,
)
from syn_domain.contexts.orchestration.domain.commands.TerminateWorkspaceCommand import (
    TerminateWorkspaceCommand,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        CapabilityType,
        IsolationBackendType,
        IsolationHandle,
        SidecarHandle,
    )

    from syn_adapters.workspace_backends.service.workspace_service import (
        WorkspaceService,
        WorkspaceServiceConfig,
    )

logger = logging.getLogger(__name__)


def create_workspace_aggregate(
    *,
    workspace_id: str,
    execution_id: str,
    workflow_id: str | None,
    phase_id: str | None,
    backend: IsolationBackendType,
    capabilities: tuple[CapabilityType, ...],
    image: str,
) -> WorkspaceAggregate:
    """Create a WorkspaceAggregate and emit the creation event.

    Args:
        workspace_id: Unique workspace ID
        execution_id: Execution ID for audit trail
        workflow_id: Optional workflow ID
        phase_id: Optional phase ID
        backend: Isolation backend type
        capabilities: Required capabilities
        image: Container image

    Returns:
        Initialized WorkspaceAggregate
    """
    aggregate = WorkspaceAggregate()
    create_cmd = CreateWorkspaceCommand(
        aggregate_id=workspace_id,
        execution_id=execution_id,
        workflow_id=workflow_id,
        phase_id=phase_id,
        isolation_backend=backend,
        capabilities=capabilities,
        image=image,
    )
    aggregate.create_workspace(create_cmd)
    return aggregate


def build_isolation_config(
    *,
    config: WorkspaceServiceConfig,
    workspace_id: str,
    execution_id: str,
    workflow_id: str | None,
    phase_id: str | None,
    extra_environment: dict[str, str] | None,
) -> IsolationConfig:
    """Build IsolationConfig with merged environment variables.

    Args:
        config: Service configuration
        workspace_id: Unique workspace ID
        execution_id: Execution ID
        workflow_id: Optional workflow ID
        phase_id: Optional phase ID
        extra_environment: Additional environment variables

    Returns:
        IsolationConfig for container creation
    """
    merged_environment = dict(config.environment or {})
    if extra_environment:
        merged_environment.update(extra_environment)

    return IsolationConfig(
        execution_id=execution_id,
        workspace_id=workspace_id,
        workflow_id=workflow_id,
        phase_id=phase_id,
        backend=config.backend,
        capabilities=config.capabilities,
        image=config.image,
        security_policy=SecurityPolicy(
            memory_limit_mb=config.memory_limit_mb,
            cpu_limit_cores=config.cpu_limit_cores,
        ),
        environment=merged_environment,
    )


async def provision_workspace(
    service: WorkspaceService,
    isolation_config: IsolationConfig,
    aggregate: WorkspaceAggregate,
    workspace_id: str,
    *,
    with_sidecar: bool,
) -> tuple[IsolationHandle, SidecarHandle | None]:
    """Provision isolation container and optional sidecar.

    Args:
        service: WorkspaceService instance
        isolation_config: Configuration for container
        aggregate: WorkspaceAggregate to record events on
        workspace_id: Workspace ID
        with_sidecar: Whether to start sidecar proxy

    Returns:
        Tuple of (isolation_handle, sidecar_handle or None)
    """
    # Create isolation container
    logger.info(
        "Creating workspace (id=%s, execution=%s)",
        workspace_id,
        isolation_config.execution_id,
    )
    isolation_handle = await service._isolation.create(isolation_config)
    aggregate.record_isolation_started(
        isolation_id=isolation_handle.isolation_id,
        isolation_type=isolation_handle.isolation_type,
    )

    # Start sidecar if requested
    sidecar_handle: SidecarHandle | None = None
    if with_sidecar:
        sidecar_config = SidecarConfig(
            workspace_id=workspace_id,
            listen_port=8080,
            allowed_hosts=service._config.allowed_hosts,
        )
        sidecar_handle = await service._sidecar.start(
            sidecar_config,
            isolation_handle,
        )
        logger.info(
            "Sidecar started (proxy=%s)",
            sidecar_handle.proxy_url,
        )

    return isolation_handle, sidecar_handle


async def cleanup_workspace(
    service: WorkspaceService,
    aggregate: WorkspaceAggregate,
    workspace_id: str,
    execution_id: str,
    *,
    isolation_handle: IsolationHandle | None,
    sidecar_handle: SidecarHandle | None,
    inject_tokens: bool,
) -> None:
    """Clean up workspace resources (tokens, sidecar, isolation).

    Args:
        service: WorkspaceService instance
        aggregate: WorkspaceAggregate
        workspace_id: Workspace ID
        execution_id: Execution ID
        isolation_handle: Handle to isolation container (if created)
        sidecar_handle: Handle to sidecar (if created)
        inject_tokens: Whether tokens were injected
    """
    logger.info("Cleaning up workspace (id=%s)", workspace_id)

    # Revoke tokens
    if inject_tokens:
        try:
            await service._token_injection.revoke(execution_id)
        except Exception as e:
            logger.warning("Failed to revoke tokens: %s", e)

    # Stop sidecar
    if sidecar_handle:
        try:
            await service._sidecar.stop(sidecar_handle)
        except Exception as e:
            logger.warning("Failed to stop sidecar: %s", e)

    # Destroy isolation
    if isolation_handle:
        try:
            await service._isolation.destroy(isolation_handle)
        except Exception as e:
            logger.warning("Failed to destroy isolation: %s", e)

    # Emit termination event
    terminate_cmd = TerminateWorkspaceCommand(
        workspace_id=workspace_id,
        reason="Execution completed",
    )
    aggregate.terminate_workspace(terminate_cmd)

    logger.info("Workspace cleaned up (id=%s)", workspace_id)
