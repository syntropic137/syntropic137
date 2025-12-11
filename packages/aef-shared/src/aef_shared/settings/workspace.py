"""Workspace isolation settings for secure agent execution.

This module provides configuration for isolated workspace backends.
All workspaces are isolated by default - these settings control HOW,
not WHETHER isolation occurs.

See ADR-021: Isolated Workspace Architecture

Environment Variables:
    AEF_WORKSPACE_* - Workspace backend configuration
    AEF_SECURITY_* - Security policies for all workspaces

Usage:
    from aef_shared.settings import get_settings

    settings = get_settings()
    backend = settings.workspace.isolation_backend
    max_memory = settings.workspace_security.max_memory
"""

from __future__ import annotations

import shutil
import sys
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class IsolationBackend(str, Enum):
    """Available isolation backends for agent workspaces.

    All backends provide isolation - the choice affects:
    - Scale: How many concurrent agents per node
    - Overhead: Memory/CPU per workspace
    - Platform: What systems support this backend

    Ordered by isolation strength:
    1. FIRECRACKER - Separate kernel (Linux only, ~125ms startup)
    2. KATA - Separate kernel via K8s (Kubernetes environments)
    3. GVISOR - User-space kernel (macOS compatible, higher overhead)
    4. DOCKER_HARDENED - Shared kernel with hardening (fallback)
    5. CLOUD - External sandbox service (E2B, Modal)
    """

    FIRECRACKER = "firecracker"
    KATA = "kata"
    GVISOR = "gvisor"
    DOCKER_HARDENED = "docker_hardened"
    CLOUD = "cloud"


class CloudProvider(str, Enum):
    """Cloud sandbox providers for overflow capacity."""

    E2B = "e2b"
    MODAL = "modal"


class WorkspaceSecuritySettings(BaseSettings):
    """Security policies applied to all isolated workspaces.

    Defaults are maximally restrictive:
    - No network access
    - Read-only root filesystem
    - Strict resource limits

    Override via AEF_SECURITY_* environment variables.
    """

    model_config = SettingsConfigDict(
        env_prefix="AEF_SECURITY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # =========================================================================
    # NETWORK ISOLATION
    # =========================================================================

    allow_network: bool = Field(
        default=False,
        description=(
            "Allow network access from workspaces. "
            "Default: False (full network isolation). "
            "Enable only if agents need to fetch dependencies or make API calls."
        ),
    )

    allowed_hosts: str = Field(
        default="",
        description=(
            "Allowlisted hosts when network is enabled (comma-separated). "
            "Empty = allow all (not recommended). "
            "Example: 'pypi.org,api.github.com'"
        ),
    )

    # =========================================================================
    # FILESYSTEM ISOLATION
    # =========================================================================

    read_only_root: bool = Field(
        default=True,
        description=(
            "Mount root filesystem as read-only. "
            "Workspace directory is always writable via tmpfs. "
            "Prevents agents from modifying system files."
        ),
    )

    max_workspace_size: str = Field(
        default="1Gi",
        description=(
            "Maximum size of workspace tmpfs. "
            "Format: Kubernetes resource format (1Gi, 512Mi, etc). "
            "Prevents agents from filling disk."
        ),
    )

    # =========================================================================
    # RESOURCE LIMITS
    # =========================================================================

    max_memory: str = Field(
        default="512Mi",
        description=(
            "Maximum memory per workspace. "
            "Format: Kubernetes resource format (512Mi, 1Gi, etc). "
            "Prevents single agent from exhausting host memory."
        ),
    )

    max_cpu: float = Field(
        default=0.5,
        ge=0.1,
        le=16.0,
        description=(
            "Maximum CPU cores per workspace. "
            "0.5 = 50% of one core. "
            "Prevents single agent from monopolizing CPU."
        ),
    )

    max_pids: int = Field(
        default=100,
        ge=10,
        le=10000,
        description=(
            "Maximum number of processes per workspace. Prevents fork bombs and process exhaustion."
        ),
    )

    max_execution_time: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description=(
            "Maximum execution time in seconds (hard limit). "
            "Default: 1 hour. Workspace is forcibly terminated after this."
        ),
    )

    # =========================================================================
    # COMPUTED PROPERTIES
    # =========================================================================

    def get_allowed_hosts_list(self) -> list[str]:
        """Get allowed hosts as a list.

        Parses the comma-separated allowed_hosts string into a list.
        """
        if not self.allowed_hosts:
            return []
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]


class WorkspaceSettings(BaseSettings):
    """Workspace isolation backend configuration.

    Controls which isolation backend to use and capacity settings.
    All workspaces are isolated - this determines HOW.

    Override via AEF_WORKSPACE_* environment variables.
    """

    model_config = SettingsConfigDict(
        env_prefix="AEF_WORKSPACE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # =========================================================================
    # BACKEND SELECTION
    # =========================================================================

    isolation_backend: IsolationBackend = Field(
        default_factory=lambda: get_default_isolation_backend(),
        description=(
            "Isolation backend to use. "
            "Default: firecracker (Linux) or gvisor (macOS). "
            "Options: firecracker, kata, gvisor, docker_hardened, cloud"
        ),
    )

    # =========================================================================
    # CAPACITY
    # =========================================================================

    pool_size: int = Field(
        default=100,
        ge=0,
        le=10000,
        description=(
            "Number of pre-warmed workspace instances. "
            "Higher = faster allocation, more memory usage. "
            "Set to 0 to disable pre-warming."
        ),
    )

    max_concurrent: int = Field(
        default=1000,
        ge=1,
        le=100000,
        description=(
            "Maximum concurrent workspaces. Requests beyond this will queue or overflow to cloud."
        ),
    )

    # =========================================================================
    # CLOUD OVERFLOW
    # =========================================================================

    enable_cloud_overflow: bool = Field(
        default=True,
        description=(
            "Enable cloud overflow when local capacity exceeded. Requires cloud_api_key to be set."
        ),
    )

    cloud_provider: CloudProvider = Field(
        default=CloudProvider.E2B,
        description="Cloud provider for overflow: e2b or modal.",
    )

    cloud_api_key: SecretStr | None = Field(
        default=None,
        description=(
            "API key for cloud sandbox provider. "
            "Required when enable_cloud_overflow is True. "
            "Get from: https://e2b.dev or https://modal.com"
        ),
    )

    cloud_template: str = Field(
        default="aef-workspace",
        description="Cloud sandbox template/environment name.",
    )

    # =========================================================================
    # DOCKER SETTINGS (gvisor, docker_hardened backends)
    # =========================================================================

    docker_image: str = Field(
        default="aef-workspace:latest",
        description=(
            "Docker image for container-based backends. "
            "Should include Python, uv, and pre-configured hooks."
        ),
    )

    docker_runtime: Literal["runsc", "runc"] = Field(
        default="runsc",
        description=(
            "Docker runtime to use. "
            "runsc = gVisor (stronger isolation), "
            "runc = native (faster, weaker isolation)"
        ),
    )

    docker_network: str = Field(
        default="none",
        description=(
            "Docker network for containers. "
            "Default: none (full network isolation). "
            "Use 'bridge' with allowed_hosts for controlled access."
        ),
    )


def get_default_isolation_backend() -> IsolationBackend:
    """Select the best available isolation backend for the current platform.

    Priority order:
    1. Firecracker (Linux with KVM) - Best isolation + scale
    2. gVisor (Docker with runsc) - macOS compatible
    3. Hardened Docker (Docker available) - Fallback

    Returns:
        IsolationBackend: The recommended backend for this platform.

    Raises:
        RuntimeError: If no isolation backend is available.
    """
    # Linux with KVM = Firecracker is best
    if sys.platform == "linux" and Path("/dev/kvm").exists():
        if shutil.which("firecracker"):
            return IsolationBackend.FIRECRACKER
        # Kata as alternative on Linux with KVM
        if _is_kata_available():
            return IsolationBackend.KATA

    # Check for gVisor Docker runtime
    if _is_gvisor_available():
        return IsolationBackend.GVISOR

    # Fall back to hardened Docker
    if _is_docker_available():
        return IsolationBackend.DOCKER_HARDENED

    # If nothing is available, default to GVISOR and let it fail at runtime
    # with a clear error message about what's needed
    return IsolationBackend.GVISOR


def _is_docker_available() -> bool:
    """Check if Docker daemon is available."""
    return shutil.which("docker") is not None


def _is_gvisor_available() -> bool:
    """Check if gVisor (runsc) runtime is available in Docker."""
    # TODO: Actually check if runsc runtime is configured in Docker
    # For now, just check if Docker is available
    return _is_docker_available()


def _is_kata_available() -> bool:
    """Check if Kata Containers runtime is available."""
    # Check for kata-runtime binary
    return shutil.which("kata-runtime") is not None
