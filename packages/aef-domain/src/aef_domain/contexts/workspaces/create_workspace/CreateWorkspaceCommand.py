"""CreateWorkspaceCommand - command to create an isolated workspace."""

from __future__ import annotations

from dataclasses import dataclass, field

from event_sourcing import Command

from aef_domain.contexts.workspaces._shared.value_objects import (
    CapabilityType,
    IsolationBackendType,
    SecurityPolicy,
)


@dataclass
class CreateWorkspaceCommand(Command):
    """Command to create a new isolated workspace.

    Attributes:
        execution_id: ID of the execution this workspace belongs to
        workflow_id: Optional workflow ID
        phase_id: Optional phase ID within workflow
        isolation_backend: Backend to use (docker, firecracker, etc.)
        capabilities: Enabled capabilities (network, git, claude, etc.)
        security_policy: Security settings (egress rules, limits)
        image: Container/VM image to use
        working_directory: Working directory path inside isolation
        enable_sidecar: Whether to start sidecar proxy (recommended for ADR-022)
        environment: Non-sensitive environment variables
        labels: Labels for tracking/filtering
        aggregate_id: Optional explicit workspace ID
    """

    execution_id: str

    # Context (optional)
    workflow_id: str | None = None
    phase_id: str | None = None

    # Backend selection
    isolation_backend: IsolationBackendType = IsolationBackendType.DOCKER_HARDENED

    # Capabilities
    capabilities: tuple[CapabilityType, ...] = (CapabilityType.FILESYSTEM,)

    # Security
    security_policy: SecurityPolicy = field(default_factory=SecurityPolicy)

    # Image/environment
    image: str = "aef-agent-runner:latest"
    working_directory: str = "/workspace"

    # Sidecar
    enable_sidecar: bool = True  # Recommended per ADR-022

    # Environment variables (non-sensitive)
    environment: dict[str, str] = field(default_factory=dict)

    # Labels for tracking
    labels: dict[str, str] = field(default_factory=dict)

    # Explicit ID (optional, auto-generated if not provided)
    aggregate_id: str | None = None
