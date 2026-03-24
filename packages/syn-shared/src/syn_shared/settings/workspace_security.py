"""Security policies for isolated agent workspaces.

See ADR-021: Isolated Workspace Architecture.
"""

from __future__ import annotations

import re

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
        description="Maximum number of processes per workspace. Prevents fork bombs and process exhaustion.",
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

    def get_allowed_hosts_list(self) -> list[str]:
        """Get allowed hosts as a list."""
        if not self.allowed_hosts:
            return []
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]

    def get_docker_memory(self) -> str:
        """Convert Kubernetes memory format (512Mi) to Docker format (512m)."""
        mem = self.max_memory.strip()
        if mem.endswith("Ki"):
            return mem[:-2] + "k"
        if mem.endswith("Mi"):
            return mem[:-2] + "m"
        if mem.endswith("Gi"):
            return mem[:-2] + "g"
        if mem.endswith("Ti"):
            return mem[:-2] + "t"
        return mem.lower()


class ContainerLoggingSettings(BaseSettings):
    """Logging configuration for container observability.

    See ADR-021: Isolated Workspace Architecture - Container Observability.

    Override via SYN_LOGGING_* environment variables.
    """

    model_config = SettingsConfigDict(
        env_prefix="SYN_LOGGING_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    level: str = Field(
        default="INFO",
        description="Minimum log level for container logs.",
    )

    format: str = Field(
        default="json",
        description="Log format: 'json' for structured, 'text' for human-readable.",
    )

    log_commands: bool = Field(
        default=True, description="Log shell commands executed in container."
    )
    log_tool_calls: bool = Field(default=True, description="Log tool calls made by agents.")
    log_api_calls: bool = Field(
        default=False,
        description="Log API calls (Claude, GitHub, etc). Disabled by default - can be verbose.",
    )

    redact_secrets: bool = Field(
        default=True,
        description="Redact sensitive data in logs (API keys, tokens, passwords).",
    )

    redaction_patterns: list[str] = Field(
        default_factory=lambda: [
            r"sk-ant-[a-zA-Z0-9-]+",
            r"sk-[a-zA-Z0-9-]+",
            r"ghp_[a-zA-Z0-9]+",
            r"github_pat_[a-zA-Z0-9_]+",
            r"gho_[a-zA-Z0-9]+",
            r"ghu_[a-zA-Z0-9]+",
            r"ghs_[a-zA-Z0-9]+",
            r"ghr_[a-zA-Z0-9]+",
            r"password=[^\s&]+",
            r"token=[^\s&]+",
            r"api_key=[^\s&]+",
            r"Bearer [a-zA-Z0-9._-]+",
        ],
        description="Regex patterns for secret redaction.",
    )

    log_file_path: str = Field(
        default="/workspace/.logs/agent.jsonl",
        description="Log file path inside container.",
    )

    max_log_size_mb: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Max log file size in MB before rotation.",
    )

    def redact(self, value: str) -> str:
        """Redact sensitive patterns from a string."""
        if not self.redact_secrets:
            return value
        result = str(value)
        for pattern in self.redaction_patterns:
            result = re.sub(pattern, "[REDACTED]", result, flags=re.IGNORECASE)
        return result
