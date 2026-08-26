"""Workspace lifecycle helpers for WorkspaceService.

Extracted from WorkspaceService.create_workspace() to reduce method complexity.
These are standalone functions that implement individual lifecycle steps.

See ADR-021, ADR-023, ADR-024.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration import (
    CreateWorkspaceCommand,
    ImageManifest,
    IsolationConfig,
    SecurityPolicy,
    SidecarConfig,
    TerminateWorkspaceCommand,
    WorkspaceAggregate,
)

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.service.workspace_service import (
        WorkspaceService,
        WorkspaceServiceConfig,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        CapabilityType,
        IsolationBackendType,
        IsolationHandle,
        SidecarHandle,
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


VERSION_JSON_PATH = "/opt/agentic/version.json"
"""Path to the version manifest inside workspace images."""


async def _read_image_manifest(
    service: WorkspaceService,
    handle: IsolationHandle,
) -> ImageManifest | None:
    """Read /opt/agentic/version.json from a running container (best-effort).

    Returns None if the image doesn't contain a version manifest (older images)
    or if the read fails for any reason. Never raises.

    The blocking Docker exec_run() call is dispatched to a thread via
    asyncio.to_thread() so it does not stall the event loop if Docker is
    slow or unresponsive.
    """
    try:
        provider = getattr(service._isolation, "_provider", None)
        if provider is None:
            return None

        container = getattr(provider, "_active_workspaces", {}).get(handle.isolation_id)
        if container is None:
            return None

        exit_code, output = await asyncio.to_thread(container.exec_run, ["cat", VERSION_JSON_PATH])
        if exit_code != 0:
            logger.debug("No version manifest in image (exit=%d)", exit_code)
            return None

        data = json.loads(output)
        return ImageManifest(
            provider=data.get("provider", ""),
            provider_version=data.get("provider_version", ""),
            components=data.get("components", {}),
            build_commit=data.get("build_commit", ""),
            built_at=data.get("built_at", ""),
            manifest_digest=data.get("manifest_digest", ""),
        )
    except Exception:
        logger.debug("Failed to read image manifest", exc_info=True)
        return None


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

    # Read image version manifest from container (best-effort)
    manifest = await _read_image_manifest(service, isolation_handle)

    aggregate.record_isolation_started(
        isolation_id=isolation_handle.isolation_id,
        isolation_type=isolation_handle.isolation_type,
        image_manifest=manifest,
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


async def _revoke_tokens(service: WorkspaceService, execution_id: str) -> None:
    """Revoke injected tokens, logging on failure."""
    try:
        await service._token_injection.revoke(execution_id)
    except Exception as e:
        logger.warning("Failed to revoke tokens: %s", e)


async def _stop_sidecar(service: WorkspaceService, sidecar_handle: SidecarHandle) -> None:
    """Stop sidecar proxy, logging on failure."""
    try:
        await service._sidecar.stop(sidecar_handle)
    except Exception as e:
        logger.warning("Failed to stop sidecar: %s", e)


async def _destroy_isolation(service: WorkspaceService, isolation_handle: IsolationHandle) -> None:
    """Destroy isolation container, logging on failure."""
    try:
        await service._isolation.destroy(isolation_handle)
    except Exception as e:
        logger.warning("Failed to destroy isolation: %s", e)


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

    if inject_tokens:
        await _revoke_tokens(service, execution_id)
    if sidecar_handle:
        await _stop_sidecar(service, sidecar_handle)
    if isolation_handle:
        await _destroy_isolation(service, isolation_handle)

    # Emit termination event
    terminate_cmd = TerminateWorkspaceCommand(
        workspace_id=workspace_id,
        reason="Execution completed",
    )
    aggregate.terminate_workspace(terminate_cmd)

    logger.info("Workspace cleaned up (id=%s)", workspace_id)
