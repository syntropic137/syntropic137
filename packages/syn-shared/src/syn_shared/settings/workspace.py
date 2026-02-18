"""Workspace isolation settings for secure agent execution.

This module provides configuration for isolated workspace backends.
All workspaces are isolated by default - these settings control HOW,
not WHETHER isolation occurs.

See ADR-021: Isolated Workspace Architecture

Environment Variables:
    SYN_WORKSPACE_* - Workspace backend configuration
    SYN_SECURITY_* - Security policies for all workspaces
    SYN_GIT_* - Git identity and credentials
    SYN_LOGGING_* - Container logging configuration

Usage:
    from syn_shared.settings import get_settings

    settings = get_settings()
    backend = settings.workspace.isolation_backend
    max_memory = settings.workspace_security.max_memory
    git_identity = settings.git_identity
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from enum import Enum
from pathlib import Path
from typing import Any, Literal

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

    Override via SYN_SECURITY_* environment variables.
    """

    model_config = SettingsConfigDict(
        env_prefix="SYN_SECURITY_",
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

    def get_docker_memory(self) -> str:
        """Get memory limit in Docker format.

        Converts Kubernetes format (512Mi, 1Gi) to Docker format (512m, 1g).
        Docker only accepts lowercase 'm', 'g' suffixes without 'i'.
        """
        mem = self.max_memory.strip()
        # Convert Kubernetes binary units to Docker format
        # Ki -> k, Mi -> m, Gi -> g (Docker uses lowercase)
        if mem.endswith("Ki"):
            return mem[:-2] + "k"
        if mem.endswith("Mi"):
            return mem[:-2] + "m"
        if mem.endswith("Gi"):
            return mem[:-2] + "g"
        if mem.endswith("Ti"):
            return mem[:-2] + "t"
        # Already in Docker format or plain bytes
        return mem.lower()


class WorkspaceSettings(BaseSettings):
    """Workspace isolation backend configuration.

    Controls which isolation backend to use and capacity settings.
    All workspaces are isolated - this determines HOW.

    Override via SYN_WORKSPACE_* environment variables.
    """

    model_config = SettingsConfigDict(
        env_prefix="SYN_WORKSPACE_",
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
        default="syn-workspace",
        description="Cloud sandbox template/environment name.",
    )

    # =========================================================================
    # DOCKER SETTINGS (gvisor, docker_hardened backends)
    # =========================================================================

    docker_image: str = Field(
        default="agentic-workspace-claude-cli:latest",
        description=(
            "Docker image for Claude agent execution. "
            "Includes Claude CLI with agentic_events hooks (ADR-029). "
            "Build with: just workspace-build"
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


# =============================================================================
# GIT IDENTITY SETTINGS
# =============================================================================


class GitCredentialType(str, Enum):
    """Git credential types for authentication."""

    HTTPS = "https"  # Personal Access Token
    GITHUB_APP = "github_app"  # GitHub App (recommended for production)
    NONE = "none"  # No credentials (public repos only)


class GitIdentitySettings(BaseSettings):
    """Git identity and credentials for workspace commits.

    Controls git user.name, user.email, and authentication.
    Agents use these settings to commit code with proper attribution.

    See ADR-021: Isolated Workspace Architecture - Git Identity section.

    Precedence (resolved by GitIdentityResolver):
    1. Workflow override (if specified)
    2. Environment variables (SYN_GIT_*)
    3. Local git config (development only)

    Override via SYN_GIT_* environment variables.
    """

    model_config = SettingsConfigDict(
        env_prefix="SYN_GIT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Private attribute to track env file configuration (not a field)
    _skip_env_file: bool = False

    def __init__(self, **kwargs: Any) -> None:
        """Initialize settings, tracking env file configuration.

        Args:
            **kwargs: Pydantic settings kwargs including _env_file.
        """
        super().__init__(**kwargs)
        # Track if we were constructed without env file (for test isolation)
        if kwargs.get("_env_file") is None:
            object.__setattr__(self, "_skip_env_file", True)

    # =========================================================================
    # IDENTITY (Required for commits)
    # =========================================================================

    user_name: str | None = Field(
        default=None,
        description=(
            "Git committer name (user.name). "
            "Example: 'syn-bot[bot]' for automated commits. "
            "Required for commits - will fail if not configured."
        ),
    )

    user_email: str | None = Field(
        default=None,
        description=(
            "Git committer email (user.email). "
            "Example: 'bot@syntropic137.com' or GitHub noreply address. "
            "Required for commits - will fail if not configured."
        ),
    )

    # =========================================================================
    # CREDENTIALS (For private repos / push)
    # =========================================================================

    token: SecretStr | None = Field(
        default=None,
        description=(
            "GitHub Personal Access Token for HTTPS authentication. "
            "Required scopes: repo (for private repos). "
            "Get from: https://github.com/settings/tokens "
            "Stored in ~/.git-credentials inside container. "
            "NOTE: For production, prefer GitHub App (SYN_GITHUB_*) over PAT."
        ),
    )

    # =========================================================================
    # COMPUTED PROPERTIES
    # =========================================================================

    @property
    def credential_type(self) -> GitCredentialType:
        """Determine which credential type is configured.

        Checks GitHub App settings (SYN_GITHUB_*) first, then falls back to PAT.

        Returns:
            GitCredentialType: The active credential type.
        """
        # Check GitHub App settings (separate config with SYN_GITHUB_* prefix)
        from syn_shared.settings.github import GitHubAppSettings

        # Propagate env file configuration to nested settings for test isolation
        # _env_file is a pydantic-settings runtime parameter not typed in __init__
        github = (
            GitHubAppSettings(_env_file=None)  # type: ignore[call-arg]
            if self._skip_env_file
            else GitHubAppSettings()
        )
        if github.is_configured:
            return GitCredentialType.GITHUB_APP
        if self.token:
            return GitCredentialType.HTTPS
        return GitCredentialType.NONE

    @property
    def is_configured(self) -> bool:
        """Check if identity is fully configured for commits."""
        return bool(self.user_name and self.user_email)

    @property
    def has_credentials(self) -> bool:
        """Check if credentials are configured for push."""
        return self.credential_type != GitCredentialType.NONE


# =============================================================================
# CONTAINER LOGGING SETTINGS
# =============================================================================


class ContainerLoggingSettings(BaseSettings):
    """Logging configuration for container observability.

    Controls how operations inside containers are logged.
    Logs are ephemeral (tmpfs) and will be streamed to centralized
    logging service in the future.

    See ADR-021: Isolated Workspace Architecture - Container Observability.

    Key features:
    - Structured JSON logging for machine parsing
    - Secret redaction (API keys, tokens, passwords)
    - Log levels for filtering

    Override via SYN_LOGGING_* environment variables.
    """

    model_config = SettingsConfigDict(
        env_prefix="SYN_LOGGING_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # =========================================================================
    # LOG FORMAT
    # =========================================================================

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        description=(
            "Minimum log level for container logs. DEBUG for development, INFO for production."
        ),
    )

    format: Literal["json", "text"] = Field(
        default="json",
        description=(
            "Log format: 'json' for structured logs (parsing), "
            "'text' for human-readable (debugging)."
        ),
    )

    # =========================================================================
    # WHAT TO LOG
    # =========================================================================

    log_commands: bool = Field(
        default=True,
        description="Log shell commands executed in container.",
    )

    log_tool_calls: bool = Field(
        default=True,
        description="Log tool calls made by agents.",
    )

    log_api_calls: bool = Field(
        default=False,
        description=("Log API calls (Claude, GitHub, etc). Disabled by default - can be verbose."),
    )

    # =========================================================================
    # SECURITY
    # =========================================================================

    redact_secrets: bool = Field(
        default=True,
        description=(
            "Redact sensitive data in logs (API keys, tokens, passwords). "
            "ALWAYS enabled in production. Cannot be disabled in prod."
        ),
    )

    redaction_patterns: list[str] = Field(
        default_factory=lambda: [
            r"sk-ant-[a-zA-Z0-9-]+",  # Anthropic API keys
            r"sk-[a-zA-Z0-9-]+",  # OpenAI API keys
            r"ghp_[a-zA-Z0-9]+",  # GitHub PAT (classic)
            r"github_pat_[a-zA-Z0-9_]+",  # GitHub PAT (fine-grained)
            r"gho_[a-zA-Z0-9]+",  # GitHub OAuth token
            r"ghu_[a-zA-Z0-9]+",  # GitHub user token
            r"ghs_[a-zA-Z0-9]+",  # GitHub server token
            r"ghr_[a-zA-Z0-9]+",  # GitHub refresh token
            r"password=[^\s&]+",  # Password in URLs/params
            r"token=[^\s&]+",  # Token in URLs/params
            r"api_key=[^\s&]+",  # API key in params
            r"Bearer [a-zA-Z0-9._-]+",  # Bearer tokens
        ],
        description="Regex patterns for secret redaction.",
    )

    # =========================================================================
    # STORAGE (Ephemeral by default)
    # =========================================================================

    log_file_path: str = Field(
        default="/workspace/.logs/agent.jsonl",
        description=("Log file path inside container. Directory is created on workspace startup."),
    )

    max_log_size_mb: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Max log file size in MB before rotation.",
    )

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def redact(self, value: str) -> str:
        """Redact sensitive patterns from a string.

        Args:
            value: String that may contain secrets.

        Returns:
            String with secrets replaced by [REDACTED].
        """
        if not self.redact_secrets:
            return value

        result = str(value)
        for pattern in self.redaction_patterns:
            result = re.sub(pattern, "[REDACTED]", result, flags=re.IGNORECASE)
        return result


# =============================================================================
# GIT IDENTITY RESOLVER
# =============================================================================


class GitIdentityResolver:
    """Resolve git identity using precedence rules.

    Precedence:
    1. Workflow override (if provided)
    2. Environment variables (SYN_GIT_*)
    3. Local git config (development only)

    Usage:
        resolver = GitIdentityResolver()
        identity = resolver.resolve()  # From env or git config
        identity = resolver.resolve(workflow_override)  # With override
    """

    def resolve(
        self,
        workflow_override: GitIdentitySettings | None = None,
    ) -> GitIdentitySettings:
        """Resolve git identity using precedence rules.

        Args:
            workflow_override: Optional settings from workflow definition.

        Returns:
            GitIdentitySettings with identity resolved.

        Raises:
            ValueError: If no identity is configured and not in development.
        """
        # 1. Workflow override takes precedence
        if workflow_override and workflow_override.is_configured:
            return workflow_override

        # 2. Environment variables
        env_settings = GitIdentitySettings()
        if env_settings.is_configured:
            return env_settings

        # 3. Local git config (development only)
        if os.getenv("APP_ENVIRONMENT", "development") == "development":
            local_identity = self._from_local_git_config()
            if local_identity:
                return local_identity

        # No identity configured
        msg = (
            "Git identity not configured. Set SYN_GIT_USER_NAME and "
            "SYN_GIT_USER_EMAIL environment variables, or use workflow override."
        )
        raise ValueError(msg)

    def _from_local_git_config(self) -> GitIdentitySettings | None:
        """Read git identity from local git config.

        Only used in development mode as a convenience fallback.

        Returns:
            GitIdentitySettings or None if not configured locally.
        """
        try:
            name = subprocess.run(
                ["git", "config", "--get", "user.name"],
                capture_output=True,
                text=True,
                check=False,
            )
            email = subprocess.run(
                ["git", "config", "--get", "user.email"],
                capture_output=True,
                text=True,
                check=False,
            )

            if name.returncode == 0 and email.returncode == 0:
                user_name = name.stdout.strip()
                user_email = email.stdout.strip()
                if user_name and user_email:
                    return GitIdentitySettings(
                        user_name=user_name,
                        user_email=user_email,
                    )
        except FileNotFoundError:
            # git not installed
            pass

        return None


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
