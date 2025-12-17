"""Value objects for workspace domain.

This module defines the core value objects for the workspace bounded context:
- Enums: IsolationBackendType, WorkspaceStatus, TokenType, CapabilityType
- Configs: IsolationConfig, SidecarConfig, SecurityPolicy
- Results: ExecutionResult, TokenInjectionResult, IsolationHandle, SidecarHandle

All value objects are immutable (frozen dataclasses) per DDD principles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime


# =============================================================================
# ENUMS
# =============================================================================


class IsolationBackendType(str, Enum):
    """Isolation backend types matching aef-shared settings."""

    FIRECRACKER = "firecracker"
    KATA = "kata"
    GVISOR = "gvisor"
    DOCKER_HARDENED = "docker_hardened"
    CLOUD = "cloud"
    MEMORY = "memory"  # For testing only
    LOCAL = "local"  # For development only (DEPRECATED)


class WorkspaceStatus(str, Enum):
    """Workspace lifecycle status."""

    PENDING = "pending"  # Command received, not yet started
    CREATING = "creating"  # Isolation being provisioned
    READY = "ready"  # Ready for command execution
    RUNNING = "running"  # Command executing
    DESTROYING = "destroying"  # Cleanup in progress
    DESTROYED = "destroyed"  # Fully cleaned up
    ERROR = "error"  # Failed state


class TokenType(str, Enum):
    """Types of tokens that can be injected into workspace."""

    ANTHROPIC = "anthropic"  # Claude API token
    GITHUB = "github"  # GitHub App installation token
    OPENAI = "openai"  # OpenAI API token (future)
    CUSTOM = "custom"  # User-provided tokens


class CapabilityType(str, Enum):
    """Workspace capabilities that can be enabled."""

    NETWORK = "network"  # Outbound network access (via sidecar)
    GIT = "git"  # Git operations (clone, push, etc.)
    CLAUDE = "claude"  # Claude API access
    FILESYSTEM = "filesystem"  # Local filesystem access
    ARTIFACTS = "artifacts"  # Artifact collection


class InjectionMethod(str, Enum):
    """How tokens are injected into workspace."""

    SIDECAR = "sidecar"  # Via sidecar proxy (preferred, ADR-022)
    ENV_VAR = "env_var"  # Direct env var (legacy, less secure)
    FILE = "file"  # Written to file (e.g., git-credentials)


# =============================================================================
# CONFIGURATION VALUE OBJECTS
# =============================================================================


@dataclass(frozen=True)
class SecurityPolicy:
    """Security policy for workspace isolation.

    Defines egress rules, resource limits, and allowed operations.
    """

    # Network egress
    allowed_hosts: tuple[str, ...] = (
        "api.anthropic.com",
        "api.github.com",
        "github.com",
    )
    allow_all_egress: bool = False  # If True, no egress filtering

    # Resource limits
    memory_limit_mb: int = 4096
    cpu_limit_cores: float = 2.0
    disk_limit_gb: int = 10
    timeout_seconds: int = 3600  # Max lifetime

    # Filesystem
    read_only_root: bool = True
    allowed_writable_paths: tuple[str, ...] = ("/workspace", "/tmp")

    # Privileges
    no_new_privileges: bool = True
    drop_capabilities: bool = True


@dataclass(frozen=True)
class IsolationConfig:
    """Configuration for creating an isolation environment.

    Contains all settings needed to provision a container/VM/sandbox.
    """

    # Identity
    execution_id: str
    workspace_id: str

    # Context (optional)
    workflow_id: str | None = None
    phase_id: str | None = None

    # Backend selection
    backend: IsolationBackendType = IsolationBackendType.DOCKER_HARDENED

    # Image/environment
    image: str = "aef-workspace-claude:latest"
    working_directory: str = "/workspace"

    # Capabilities
    capabilities: tuple[CapabilityType, ...] = (CapabilityType.FILESYSTEM,)

    # Security
    security_policy: SecurityPolicy = field(default_factory=SecurityPolicy)

    # Environment variables (non-sensitive)
    environment: Mapping[str, str] = field(default_factory=dict)

    # Labels for tracking
    labels: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SidecarConfig:
    """Configuration for sidecar proxy.

    The sidecar handles:
    - Token injection into requests (ADR-022)
    - Egress filtering
    - Rate limiting
    - Request/response logging
    """

    # Identity
    workspace_id: str

    # Proxy settings
    listen_port: int = 8080
    proxy_image: str = "aef-sidecar-proxy:latest"

    # Token injection targets
    anthropic_endpoint: str = "api.anthropic.com"
    github_endpoint: str = "api.github.com"

    # Rate limiting
    rate_limit_requests_per_minute: int = 100
    rate_limit_tokens_per_minute: int = 100000

    # Egress allowlist
    allowed_hosts: tuple[str, ...] = (
        "api.anthropic.com",
        "api.github.com",
        "github.com",
    )


# =============================================================================
# RESULT VALUE OBJECTS (returned from ports)
# =============================================================================


@dataclass(frozen=True)
class IsolationHandle:
    """Handle to an isolation instance (container/VM/sandbox).

    Returned by IsolationBackendPort.create() and used for subsequent operations.

    Note on paths:
    - workspace_path: Path inside the container (e.g., /workspace)
    - host_workspace_path: Path on the host that is mounted into the container

    The host_workspace_path is used when the agent runs on the host machine
    (like claude-agent-sdk) and needs to access files that will be visible
    inside the container.
    """

    isolation_id: str  # Container ID, VM ID, etc.
    isolation_type: str  # "docker", "firecracker", "e2b", "memory"
    proxy_url: str | None = None  # Sidecar proxy URL if applicable
    workspace_path: str | None = None  # Path to workspace inside isolation
    host_workspace_path: str | None = None  # Path on host mounted into container


@dataclass(frozen=True)
class SidecarHandle:
    """Handle to a running sidecar proxy.

    Returned by SidecarPort.start() and used to stop/manage the sidecar.
    """

    sidecar_id: str  # Container ID
    proxy_url: str  # URL for proxy (e.g., http://localhost:8080)
    started_at: datetime


@dataclass(frozen=True)
class TokenInjectionResult:
    """Result of token injection operation.

    Returned by TokenInjectionPort.inject().
    """

    success: bool
    tokens_injected: tuple[TokenType, ...]
    injection_method: InjectionMethod
    ttl_seconds: int | None = None  # Time until tokens expire
    error_message: str | None = None


@dataclass(frozen=True)
class ExecutionResult:
    """Result of command execution in workspace.

    Returned by IsolationBackendPort.execute().
    """

    exit_code: int
    success: bool
    duration_ms: float
    stdout: str = ""
    stderr: str = ""
    stdout_lines: int = 0
    stderr_lines: int = 0
    timed_out: bool = False


@dataclass(frozen=True)
class Artifact:
    """An artifact collected from workspace.

    Represents a file or output collected for persistence.
    """

    name: str
    path: str  # Path inside workspace
    size_bytes: int
    content_type: str = "application/octet-stream"
    checksum: str | None = None  # SHA-256


@dataclass(frozen=True)
class ArtifactCollectionResult:
    """Result of artifact collection operation."""

    success: bool
    artifacts: tuple[Artifact, ...]
    total_size_bytes: int
    error_message: str | None = None
