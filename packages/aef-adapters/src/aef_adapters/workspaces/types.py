"""Isolated workspace types - data structures for isolated agent execution.

These types extend the base workspace types with isolation-specific
metadata and tracking.

See ADR-021: Isolated Workspace Architecture
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from aef_shared.workspace_paths import (
    WORKSPACE_CONTEXT_DIR,
    WORKSPACE_HOOKS_DIR,
    WORKSPACE_OUTPUT_DIR,
    WORKSPACE_ROOT,
)

if TYPE_CHECKING:
    from pathlib import Path

    from aef_adapters.agents.agentic_types import WorkspaceConfig
    from aef_shared.settings import IsolationBackend, WorkspaceSecuritySettings
    from aef_shared.settings.workspace import GitIdentitySettings


@dataclass
class IsolatedWorkspace:
    """An active isolated workspace for agent execution.

    Extends the base Workspace with isolation-specific metadata:
    - Which isolation backend is in use
    - Container/VM/sandbox identifiers
    - Resource usage tracking

    All workspaces in AEF are isolated by default.
    """

    path: Path
    config: WorkspaceConfig

    # Isolation metadata
    isolation_backend: IsolationBackend
    container_id: str | None = None  # Docker container ID
    vm_id: str | None = None  # Firecracker MicroVM ID
    sandbox_id: str | None = None  # Cloud sandbox ID (E2B/Modal)

    # Security settings applied to this workspace
    security: WorkspaceSecuritySettings | None = None

    # Resource usage tracking
    memory_used_bytes: int = 0
    cpu_time_seconds: float = 0.0
    network_bytes_in: int = 0
    network_bytes_out: int = 0

    # Lifecycle timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    terminated_at: datetime | None = None

    @property
    def analytics_path(self) -> Path:
        """Path to the analytics events file."""
        return self.path / self.config.analytics_path

    @property
    def context_dir(self) -> Path:
        """Directory for injected context files.

        Uses WORKSPACE_CONTEXT_DIR constant for consistency with agent-runner.
        """
        # Get relative path from container root (e.g., ".context")
        rel_path = WORKSPACE_CONTEXT_DIR.relative_to(WORKSPACE_ROOT)
        return self.path / str(rel_path)

    @property
    def output_dir(self) -> Path:
        """Directory for agent outputs.

        Uses WORKSPACE_OUTPUT_DIR constant for consistency with agent-runner.
        This is where the agent writes artifacts that get collected after execution.
        """
        # Get relative path from container root (e.g., "artifacts")
        rel_path = WORKSPACE_OUTPUT_DIR.relative_to(WORKSPACE_ROOT)
        return self.path / str(rel_path)

    @property
    def hooks_dir(self) -> Path:
        """Directory containing hook handlers.

        Uses WORKSPACE_HOOKS_DIR constant for consistency with agent-runner.
        """
        # Get relative path from container root (e.g., ".claude/hooks")
        rel_path = WORKSPACE_HOOKS_DIR.relative_to(WORKSPACE_ROOT)
        return self.path / str(rel_path)

    @property
    def isolation_id(self) -> str | None:
        """Get the isolation identifier (container_id, vm_id, or sandbox_id)."""
        return self.container_id or self.vm_id or self.sandbox_id

    @property
    def is_running(self) -> bool:
        """Check if the workspace is currently running."""
        return self.started_at is not None and self.terminated_at is None

    @property
    def duration_seconds(self) -> float | None:
        """Get the duration in seconds (or None if not yet started)."""
        if self.started_at is None:
            return None
        end_time = self.terminated_at or datetime.now(UTC)
        return (end_time - self.started_at).total_seconds()

    def mark_started(self) -> None:
        """Mark the workspace as started."""
        self.started_at = datetime.now(UTC)

    def mark_terminated(self) -> None:
        """Mark the workspace as terminated."""
        self.terminated_at = datetime.now(UTC)

    def update_resource_usage(
        self,
        *,
        memory_bytes: int | None = None,
        cpu_seconds: float | None = None,
        network_in: int | None = None,
        network_out: int | None = None,
    ) -> None:
        """Update resource usage tracking."""
        if memory_bytes is not None:
            self.memory_used_bytes = memory_bytes
        if cpu_seconds is not None:
            self.cpu_time_seconds = cpu_seconds
        if network_in is not None:
            self.network_bytes_in = network_in
        if network_out is not None:
            self.network_bytes_out = network_out


@dataclass(frozen=True)
class IsolatedWorkspaceConfig:
    """Extended workspace configuration with isolation settings.

    Wraps a WorkspaceConfig with additional isolation-specific settings.

    Attributes:
        base_config: The underlying workspace configuration
        security: Optional security settings override
        isolation_backend: Optional backend override (None = use default)
        git_identity_override: Optional git identity override for this workflow.
            If set, takes precedence over environment variables.
        execution_id: Unique identifier for this execution, used for token tracking
            and event correlation. If not provided, derived from session_id.
    """

    base_config: WorkspaceConfig
    security: WorkspaceSecuritySettings | None = None
    isolation_backend: IsolationBackend | None = None  # None = use default
    git_identity_override: GitIdentitySettings | None = None  # Workflow override
    execution_id: str | None = None  # For token tracking and event correlation

    @property
    def session_id(self) -> str:
        """Delegate to base config."""
        return self.base_config.session_id

    @property
    def workflow_id(self) -> str | None:
        """Delegate to base config."""
        return self.base_config.workflow_id

    @property
    def phase_id(self) -> str | None:
        """Delegate to base config."""
        return self.base_config.phase_id

    @property
    def effective_execution_id(self) -> str:
        """Get execution ID for token tracking (falls back to session_id)."""
        return self.execution_id or self.base_config.session_id
